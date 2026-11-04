"""Open Orion PROD in a native window (Windows). Run from the production clone only.

Same behaviour as desktop/app.py, for production: starts PostgreSQL and the prod
server if they are down (hidden, no console window), opens Orion in a native window,
and stops the server it started when the window closes.

Production is one uvicorn process that serves the built UI and the API, so there is
no Vite server and no --reload here.
"""

from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from ctypes import wintypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
ICON = REPO_ROOT / "desktop" / "OrionProd.ico"
LOG_PATH = REPO_ROOT / "data" / "prod-desktop.log"
SERVER_LOG = REPO_ROOT / "data" / "prod-server.log"
STORAGE_PATH = REPO_ROOT / "data" / "prod-desktop-webview"
TITLE = "Orion PROD"
APP_ID = "PrakashSecurities.Orion.Prod"
MAX_LOG_BYTES = 2_000_000

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE,
    wintypes.LPCWSTR,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]

_server: subprocess.Popen | None = None
_server_log = None


def _log(message: str) -> None:
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}\n")
    except OSError:
        pass


def _dialog(message: str) -> None:
    user32.MessageBoxW(0, f"{message}\n\nDetails: {LOG_PATH}", TITLE, 0x10)


def _trim(path: Path) -> None:
    try:
        if path.is_file() and path.stat().st_size > MAX_LOG_BYTES:
            path.unlink()
    except OSError:
        pass


def _read_env() -> dict[str, str]:
    """Values from this folder's .env. The server loads .env itself; this is for the launcher."""
    values: dict[str, str] = {}
    env_file = REPO_ROOT / ".env"
    if not env_file.is_file():
        return values
    for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


def wait_http(url: str, timeout: float = 120) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if http_ok(url):
            return True
        if _server is not None and _server.poll() is not None:
            return False  # the server we started has already exited
        time.sleep(0.5)
    return False


def _powershell() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return str(Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def ensure_postgres(host: str, port: int) -> bool:
    if port_open(host, port):
        return True
    _log("PostgreSQL not ready; trying to start the service")
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
        creationflags=CREATE_NO_WINDOW,
    )
    # Right after a reboot the service may still be coming up.
    for _ in range(60):
        if port_open(host, port):
            return True
        time.sleep(1)
    return False


def start_server(port: int) -> None:
    global _server, _server_log
    _trim(SERVER_LOG)
    _server_log = SERVER_LOG.open("a", encoding="utf-8")
    command = [
        str(VENV_PYTHON),
        "-m",
        "uvicorn",
        "app.main:app",
        "--app-dir",
        "backend",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
    ]
    _server = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=dict(os.environ, ORION_SERVE_FRONTEND="1"),
        stdout=_server_log,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
    )
    _log(f"started prod server pid={_server.pid} on port {port}")


def stop_server() -> None:
    if _server is None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(_server.pid), "/T", "/F"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    if _server_log:
        _server_log.close()
    _log("stopped the prod server we started")


def already_running() -> bool:
    """One Orion PROD window at a time: a second launch just raises the first."""
    kernel32.CreateMutexW(None, False, "Local\\" + APP_ID)
    if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
        return False
    hwnd = user32.FindWindowW(None, TITLE)
    if hwnd:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return True


def set_window_icon() -> None:
    """Give the window and its taskbar button the PROD icon instead of Python's."""
    if not ICON.is_file():
        return
    hwnd = None
    for _ in range(40):
        hwnd = user32.FindWindowW(None, TITLE)
        if hwnd:
            break
        time.sleep(0.1)
    if not hwnd:
        return
    for which, size in ((1, 48), (0, 16)):  # ICON_BIG, ICON_SMALL
        handle = user32.LoadImageW(None, str(ICON), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        if handle:
            user32.SendMessageW(hwnd, 0x0080, which, handle)  # WM_SETICON


def main() -> int:
    (REPO_ROOT / "data").mkdir(parents=True, exist_ok=True)
    _trim(LOG_PATH)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    if already_running():
        return 0
    _log("Orion PROD launching")

    settings = _read_env()
    if settings.get("ORION_ENV") != "production":
        _dialog(
            f"ORION_ENV is not 'production' in {REPO_ROOT}\\.env.\n"
            "This launcher is for the production folder. Use the Orion shortcut for development."
        )
        return 1
    if not VENV_PYTHON.is_file() or not (REPO_ROOT / "frontend" / "dist" / "index.html").is_file():
        _dialog(f"Production is not built yet. In PowerShell run:\n\ncd {REPO_ROOT}\n.\\scripts\\deploy.ps1")
        return 1

    port = int(settings.get("ORION_API_PORT") or 8100)
    db_host = settings.get("ORION_DB_HOST") or "localhost"
    db_port = int(settings.get("ORION_DB_PORT") or 5432)
    url = f"http://127.0.0.1:{port}"

    if not ensure_postgres(db_host, db_port):
        _dialog("PostgreSQL is not running. Start it with:\n\nStart-Service postgresql-x64-18")
        return 1

    if http_ok(f"{url}/api/health"):
        _log("prod server already running; using it")
    else:
        if port_open("127.0.0.1", port):
            _dialog(f"Port {port} is in use by something that is not Orion PROD.")
            return 1
        start_server(port)
        if not wait_http(f"{url}/api/health"):
            stop_server()
            _dialog(f"The Orion PROD server did not start. Check {SERVER_LOG}")
            return 1
        _log("prod server is up")

    try:
        import webview
    except ImportError:
        stop_server()
        _dialog("The window helper is missing. Run:\n\n.\\scripts\\install-prod-desktop-app.ps1")
        return 1

    # pywebview cancels every download unless this is on. With it on, a download (an Excel export,
    # a bill PDF) opens a Save As dialog that starts in the Downloads folder.
    webview.settings["ALLOW_DOWNLOADS"] = True

    STORAGE_PATH.mkdir(parents=True, exist_ok=True)
    boot_url = f"{url}/?boot={uuid.uuid4().hex}"
    _log(f"opening window {boot_url}")
    from orion_windows import WindowBridge

    window = webview.create_window(
        TITLE,
        boot_url,
        js_api=WindowBridge(url, TITLE, webview),  # lets the page open a second window ("open in a new tab")
        width=1440,
        height=900,
        min_size=(960, 640),
        text_select=True,
        confirm_close=True,
        localization={
            "global.quitConfirmation": "Close Orion PROD? You will need to sign in again next time.",
            "global.quit": "Close",
            "global.cancel": "Cancel",
        },
    )

    def shown() -> None:
        _log("window shown")
        try:
            set_window_icon()
        except Exception as exc:
            _log(f"could not set window icon: {exc!r}")

    window.events.shown += shown
    try:
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(STORAGE_PATH))
    finally:
        if _server is not None:
            _log("window closed; stopping the server we started")
            stop_server()
        else:
            _log("window closed; left the existing server running")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        _log(traceback.format_exc())
        stop_server()
        _dialog(f"Orion PROD could not open a window:\n\n{exc}")
        sys.exit(1)
