"""Open Orion in a native window, using the same local site as the browser."""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
REPO_ROOT = Path(__file__).resolve().parents[1]
API_PORT = int(os.environ.get("ORION_API_PORT", "8000"))
FRONTEND_PORT = int(os.environ.get("ORION_FRONTEND_PORT", "5173"))
FRONTEND_URL = f"http://127.0.0.1:{FRONTEND_PORT}"
LOG_PATH = REPO_ROOT / "data" / "desktop.log"
STORAGE_PATH = REPO_ROOT / "data" / "desktop-webview"

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)

_children: list[subprocess.Popen] = []
_log_handle = None


def _load_env() -> None:
    env_file = REPO_ROOT / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _prepare_path() -> None:
    if IS_WINDOWS:
        extras = []
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        extras.append(os.path.join(program_files, "nodejs"))
        for version in range(18, 13, -1):
            extras.append(os.path.join(program_files, "PostgreSQL", str(version), "bin"))
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            extras.extend(
                [
                    os.path.join(local_app, "Programs", "Python", "Python312"),
                    os.path.join(local_app, "Programs", "Python", "Python312", "Scripts"),
                    os.path.join(local_app, "Programs", "Python", "Python313"),
                    os.path.join(local_app, "Programs", "Python", "Python313", "Scripts"),
                ]
            )
        current = os.environ.get("PATH", "")
        os.environ["PATH"] = os.pathsep.join([path for path in extras if path] + [current])
        return

    extras = ["/opt/homebrew/bin", "/usr/local/bin"]
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = ":".join(extras + [current])
    macos_env = REPO_ROOT / "scripts" / "macos_python_env.sh"
    if macos_env.is_file():
        exported = subprocess.run(
            ["bash", "-c", f"source '{macos_env}' && echo DYLD_LIBRARY_PATH=\"$DYLD_LIBRARY_PATH\""],
            check=False,
            capture_output=True,
            text=True,
        )
        for line in exported.stdout.splitlines():
            if line.startswith("DYLD_LIBRARY_PATH=") and line.split("=", 1)[1]:
                os.environ["DYLD_LIBRARY_PATH"] = line.split("=", 1)[1]


def _log(message: str) -> None:
    global _log_handle
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}  {message}\n"
    if _log_handle:
        _log_handle.write(line)
        _log_handle.flush()


def _dialog(message: str) -> None:
    if IS_WINDOWS:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "Orion", 0x10)
        return
    subprocess.run(
        [
            "osascript",
            "-e",
            "on run argv",
            "-e",
            'display dialog (item 1 of argv) buttons {"OK"} default button 1 with title "Orion"',
            "-e",
            "end run",
            message,
        ],
        check=False,
    )


def _venv_python() -> Path:
    if IS_WINDOWS:
        return REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    return REPO_ROOT / ".venv" / "bin" / "python"


def _install_hint() -> str:
    if IS_WINDOWS:
        return r".\scripts\install-windows.ps1"
    return "bash scripts/install-mac.sh"


def _desktop_install_hint() -> str:
    if IS_WINDOWS:
        return r".\scripts\install-desktop-app.ps1"
    return "bash scripts/install-desktop-app.sh"


def _postgres_hint() -> str:
    if IS_WINDOWS:
        return "Start-Service postgresql-x64-18"
    return "brew services start postgresql@18"


def _hide_console() -> None:
    if not IS_WINDOWS:
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def wait_http(url: str, timeout: float = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1.5)
            return True
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            time.sleep(0.4)
    return False


def postgres_ready() -> bool:
    host = os.environ.get("ORION_DB_HOST", "localhost")
    port = os.environ.get("ORION_DB_PORT", "5432")
    pg_isready = shutil.which("pg_isready") or shutil.which("pg_isready.exe")
    if pg_isready:
        return (
            subprocess.run(
                [pg_isready, "-h", host, "-p", str(port), "-q"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )
    try:
        with socket.create_connection((host, int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def _powershell() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return str(Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def ensure_postgres() -> bool:
    if postgres_ready():
        return True
    _log("PostgreSQL not ready; trying to start the service")
    if IS_WINDOWS:
        subprocess.run(
            [
                _powershell(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue | "
                "Where-Object { $_.Status -ne 'Running' } | "
                "ForEach-Object { Start-Service $_.Name }",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )
    else:
        subprocess.run(
            ["brew", "services", "start", "postgresql@18"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["brew", "services", "start", "postgresql"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    for _ in range(30):
        if postgres_ready():
            return True
        time.sleep(1)
    return postgres_ready()


def _spawn(command: list[str], cwd: Path | None = None) -> subprocess.Popen:
    assert _log_handle is not None
    kwargs: dict = {
        "cwd": cwd or REPO_ROOT,
        "stdout": _log_handle,
        "stderr": subprocess.STDOUT,
    }
    if IS_WINDOWS:
        kwargs["creationflags"] = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(command, **kwargs)
    _children.append(proc)
    _log(f"started {' '.join(command)} pid={proc.pid}")
    return proc


def start_api() -> subprocess.Popen:
    if IS_WINDOWS:
        return _spawn(
            [
                str(_venv_python()),
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                "backend",
                "--host",
                "0.0.0.0",
                "--port",
                str(API_PORT),
                "--reload",
            ]
        )
    return _spawn(["bash", str(REPO_ROOT / "scripts" / "start-api.sh")])


def start_frontend() -> subprocess.Popen:
    if IS_WINDOWS:
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            raise FileNotFoundError("Node.js/npm was not found on PATH")
        return _spawn([npm, "run", "dev"], cwd=REPO_ROOT / "frontend")
    return _spawn(["bash", str(REPO_ROOT / "scripts" / "start-frontend.sh")])


def stop_started_servers() -> None:
    for proc in _children:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            continue
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    deadline = time.time() + 4
    for proc in _children:
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        if proc.poll() is None and not IS_WINDOWS:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass


def main() -> int:
    global _log_handle

    _hide_console()
    _prepare_path()
    _load_env()
    (REPO_ROOT / "data").mkdir(parents=True, exist_ok=True)
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)
    _log_handle = LOG_PATH.open("a", encoding="utf-8")
    _log("Orion desktop launching")

    if not _venv_python().is_file():
        _dialog(f"Orion is not installed yet. In PowerShell or Terminal run:\n\n{_install_hint()}")
        return 1

    if IS_WINDOWS and not (REPO_ROOT / "frontend" / "node_modules").is_dir():
        _dialog(f"Frontend packages are missing. In PowerShell run:\n\n{_install_hint()}")
        return 1

    if not ensure_postgres():
        _dialog(f"PostgreSQL is not running. Start it with:\n\n{_postgres_hint()}")
        return 1

    started_any = False
    if not port_open(API_PORT):
        start_api()
        started_any = True
    if not port_open(FRONTEND_PORT):
        start_frontend()
        started_any = True

    if not wait_http(f"http://127.0.0.1:{API_PORT}/api/health"):
        _dialog("The Orion API did not start. Check data/desktop.log in the project folder.")
        if started_any:
            stop_started_servers()
        return 1
    if not wait_http(FRONTEND_URL):
        _dialog("The Orion window could not reach the site. Check data/desktop.log.")
        if started_any:
            stop_started_servers()
        return 1

    try:
        import webview
    except ImportError:
        _dialog(f"The window helper is missing. Run:\n\n{_desktop_install_hint()}")
        if started_any:
            stop_started_servers()
        return 1

    # pywebview cancels every download unless this is on. With it on, a download (an Excel export,
    # a bill PDF) opens a Save As dialog that starts in the Downloads folder.
    webview.settings["ALLOW_DOWNLOADS"] = True

    boot_url = f"{FRONTEND_URL}/?boot={uuid.uuid4().hex}"
    _log(f"opening window {boot_url}")
    from orion_windows import WindowBridge

    window = webview.create_window(
        "Orion",
        boot_url,
        js_api=WindowBridge(FRONTEND_URL, "Orion", webview),  # lets the page open a second window ("open in a new tab")
        width=1440,
        height=900,
        min_size=(960, 640),
        text_select=True,
        confirm_close=True,
        localization={
            "global.quitConfirmation": "Close Orion? You will need to sign in again next time.",
            "global.quit": "Close",
            "global.cancel": "Cancel",
        },
    )

    def bring_forward() -> None:
        _log("window shown")
        if IS_WINDOWS:
            return
        try:
            from AppKit import NSApplication

            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception as exc:
            _log(f"could not raise window: {exc}")

    window.events.shown += bring_forward
    gui = "edgechromium" if IS_WINDOWS else "cocoa"
    try:
        webview.start(gui=gui, private_mode=False, storage_path=str(STORAGE_PATH))
    finally:
        # Next launch already signs out via ?boot=. Do not evaluate_js on the
        # closing event — WKWebView deadlocks on the Cocoa UI thread and the
        # window never finishes quitting.
        if started_any:
            _log("window closed; stopping servers we started")
            stop_started_servers()
        else:
            _log("window closed; left existing servers running")
        _log_handle.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        import traceback

        details = traceback.format_exc()
        try:
            (REPO_ROOT / "data").mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(details)
        except OSError:
            pass
        _dialog(f"Orion could not open a window:\n\n{exc}")
        sys.exit(1)
