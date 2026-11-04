# Orion

The internal workspace of Prakash Securities: operational records, dashboards, tax invoices, a copy of the
Tally books, and team chat.

React (Vite, TypeScript) frontend, FastAPI backend, one PostgreSQL database. It runs on a single Windows PC,
with dev and prod side by side.

## Start here

| You want to | Read |
|---|---|
| Set up a machine | [README-WINDOWS.md](README-WINDOWS.md) (macOS: `bash scripts/install-mac.sh`) |
| Build a feature and release it | [DEVELOPMENT.md](DEVELOPMENT.md) |
| Understand dev vs prod and deploying | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Understand how the app is built | [docs/architecture.md](docs/architecture.md) |
| Know what each feature does and its rules | [docs/features.md](docs/features.md) |
| Know what else a change affects | [docs/change-impact.md](docs/change-impact.md) |
| Work on it with an AI coding agent | [AGENTS.md](AGENTS.md) |

## Quick start (Windows)

```powershell
.\scripts\install-windows.ps1     # once: tools, virtualenv, .env, database, frontend packages
.\scripts\start-modern.ps1        # API on :8000, UI on http://localhost:5173
```

Sign in with the admin account from `.env`. The database starts empty.

## Checks before a pull request

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests
cd frontend; npx tsc -b; npm run build
```
