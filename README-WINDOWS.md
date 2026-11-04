# Orion on Windows

Setup guide for running Orion (React + FastAPI) on Windows with local PostgreSQL and optional Tailscale access.

## What you need

| Tool | Purpose | Install |
|------|---------|---------|
| Python 3.12 | Backend | `winget install Python.Python.3.12` |
| Node.js LTS | React frontend | `winget install OpenJS.NodeJS.LTS` |
| PostgreSQL 18 | Database | `winget install PostgreSQL.PostgreSQL.18` |
| pgAdmin 4 | DB GUI (optional) | `winget install PostgreSQL.pgAdmin` |
| Tailscale | Remote access (optional) | `winget install Tailscale.Tailscale` |

## One-command setup

Open **PowerShell** in the repo root and run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\scripts\install-windows.ps1
```

This will:

1. Install Python, Node, PostgreSQL, and pgAdmin via winget (if missing)
2. Create a Python virtualenv (`.venv`) and install dependencies
3. Copy `.env.example` → `.env`
4. Create the `orion` database and its empty schema
5. Run `npm install` in `frontend/`

During PostgreSQL install, you will be asked to set a **postgres superuser password**. Add that password to `.env`:

```env
ORION_POSTGRES_SUPER_PASSWORD=the-password-you-chose
```

Also change the app secrets in `.env` before exposing the app on Tailscale:

```env
ORION_DB_PASSWORD=change-me-strong-password
ORION_SESSION_SECRET=change-me-to-a-long-random-string
ORION_ADMIN_PASSWORD=change-me-admin-password
```

## Start the app (desktop window)

Same idea as the Mac `Orion.app`: one shortcut starts PostgreSQL, the API, and the site in a native window. No terminal.

```powershell
.\scripts\install-desktop-app.ps1
```

That adds **Orion** to the Desktop and Start menu. Double-click it after that.

To also open Orion when you sign in to Windows:

```powershell
.\scripts\install-desktop-app.ps1 -Startup
```

From PowerShell without a shortcut:

```powershell
.\scripts\start-desktop.ps1
```

Sign in with the admin credentials from `.env` (`ORION_ADMIN_USERNAME` / `ORION_ADMIN_PASSWORD`).

Downloading a file in this window (an Excel export, a bill PDF) opens a Save As dialog that starts in your
Downloads folder.

## Start from PowerShell (two console windows)

```powershell
.\scripts\start-modern.ps1
```

Opens two windows:

- **API** — http://127.0.0.1:8000
- **Frontend** — http://localhost:5173

Or run services separately:

```powershell
.\scripts\start-api.ps1
.\scripts\start-frontend.ps1
```

## PostgreSQL & pgAdmin

After install:

- **Service name:** `postgresql-x64-18` (start/stop in Windows Services)
- **Default superuser:** `postgres`
- **App database:** `orion` (user `orion_user`, password from `.env`)
- **pgAdmin:** connect to `localhost:5432` as `postgres`, then browse the `orion` database

Re-run database init anytime (idempotent):

```powershell
.\scripts\init_db_windows.ps1
```

## Tailscale (same as Mac)

1. Install and sign in: `winget install Tailscale.Tailscale`
2. Start Orion (desktop shortcut, `.\scripts\start-desktop.ps1`, or `.\scripts\start-modern.ps1`)
3. Other devices on your tailnet can open `http://<your-tailscale-ip>:5173`
4. Optional HTTPS via Tailscale Serve:

```powershell
.\scripts\tailscale-serve.ps1
```

Find your Tailscale IP:

```powershell
tailscale ip -4
```

## Troubleshooting

**`python` not found after install**  
Close and reopen PowerShell so PATH updates, or run `Refresh-Path` from `scripts\windows-common.ps1`.

**PostgreSQL not accepting connections**  
Start the service:

```powershell
Start-Service postgresql-x64-18
```

**Database init fails with authentication error**  
Set `ORION_POSTGRES_SUPER_PASSWORD` in `.env` to the password you chose when installing PostgreSQL.

**Execution policy blocks scripts**

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**Already installed deps manually**

```powershell
.\scripts\install-windows.ps1 -SkipWinget
```

**Re-init DB only**

```powershell
.\scripts\init_db_windows.ps1
```

## Mac vs Windows

| Mac | Windows |
|-----|---------|
| `bash scripts/install-mac.sh` | `.\scripts\install-windows.ps1` |
| `bash scripts/install-desktop-app.sh` | `.\scripts\install-desktop-app.ps1` |
| `open Orion.app` | Desktop / Start menu **Orion** shortcut |
| `bash scripts/start-modern.sh` | `.\scripts\start-modern.ps1` |
| `brew services start postgresql@18` | `Start-Service postgresql-x64-18` |
| `bash scripts/init_db_mac.sh` | `.\scripts\init_db_windows.ps1` |

The app reads the same `.env` on both platforms. Set `ORION_DB_HOST=localhost` for local PostgreSQL on Windows.
