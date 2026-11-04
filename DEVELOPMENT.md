# Orion development guide: from power-on to a live release

This is the step-by-step guide for building a new feature and getting it to production.
`DEPLOYMENT.md` is the technical reference for the prod setup. This file is the day-to-day runbook.

---

## 1. The big picture

```
   YOUR PC (one Windows machine)
   ┌────────────────────────────────────┐        ┌─────────────────────────┐
   │ DEV   F:\prakashSecurities-main\   │  push  │ GitHub                  │
   │       prakashSecurities-main       │ ─────► │ shaileshmishraa/        │
   │  UI  :5173   API :8000   DB orion  │  PR    │ prakashSecuritiesOrion  │
   └────────────────────────────────────┘ merge  │        (main)           │
                                                 └───────────┬─────────────┘
   ┌────────────────────────────────────┐   deploy.ps1       │
   │ PROD  C:\orion-prod                │ ◄──────────────────┘
   │  UI + API :8100    DB orion_prod   │   (pulls main/tag, builds, restarts)
   └────────────────────────────────────┘
        both use the same PostgreSQL server (service postgresql-x64-18)
```

| | DEV | PROD |
|---|---|---|
| Folder | `F:\prakashSecurities-main\prakashSecurities-main` | `C:\orion-prod` |
| Database | `orion` | `orion_prod` |
| URLs | UI http://localhost:5173, API http://127.0.0.1:8000 | http://127.0.0.1:8100 (UI and API together) |
| You may | edit code, break things, test | **never edit by hand**, only deploy |
| Gets code from | your edits | GitHub `main` via `deploy.ps1` |
| `.env` | dev values | prod values (`ORION_ENV=production`) |

**Golden rule:** code moves one way only. Dev folder → GitHub (pull request) → prod (`deploy.ps1`).
You never copy files into `C:\orion-prod` and never edit them there.

> The dev folder is the **inner** `prakashSecurities-main`. The outer `F:\prakashSecurities-main` is not a git repo.

---

## 2. Starting work after everything was off

### Step 1: Make sure PostgreSQL is running
It starts automatically with Windows (service `postgresql-x64-18`, startup type Automatic). To check:
```powershell
Get-Service postgresql-x64-18
```
If it says `Stopped`: `Start-Service postgresql-x64-18` (run PowerShell as Administrator).

### Step 2: Start Tally Prime (only if you will test Tally sync)
Open Tally Prime and open the company (F1). Its XML server must answer on port 9000. Skip this if you are
not testing the Tally sync.

### Step 3: Open a terminal in the DEV folder
```powershell
cd F:\prakashSecurities-main\prakashSecurities-main
```
Or open that folder in VS Code / Cursor and use its terminal. Check the prompt ends with
`...\prakashSecurities-main\prakashSecurities-main`.

### Step 4: Get the latest code and start a branch
```powershell
git checkout main
git pull origin main
git checkout -b feature/short-name
```
- Pick a name that says what you build: `feature/attendance-report`, `fix/bill-total-rounding`.
- Never develop on `main`. If `git status` shows you are on `main` with edits, run
  `git checkout -b feature/short-name` first. Your edits come along.

### Step 5: Start the dev app (choose ONE way)

**Option A: the Orion desktop app** (what you normally use). It starts the API and the Vite dev server if
they are not already running.
```powershell
.\scripts\start-desktop.ps1
```
**Option B: two terminal windows**
```powershell
.\scripts\start-modern.ps1
```
Then open http://localhost:5173 and sign in with your dev admin account (credentials are in the dev `.env`).

Check the API: http://127.0.0.1:8000/api/health must return `{"status":"ok"}`.

### Step 6: Start PROD only if you need it
You do not need prod running while developing.

**Normal way: the Orion PROD desktop shortcut** (the shield with the red PROD badge). Double-click it. It starts
PostgreSQL and the prod server in the background if they are not running, then opens prod in its own window.
Closing that window stops the prod server it started. The first time on a PC, install the shortcut once
(see `DEPLOYMENT.md`, "One-time production setup").

**Without the window** (for example when prod must stay up for other devices on the network):
```powershell
cd C:\orion-prod
.\scripts\start-prod.ps1
```
Leave that window open, closing it stops prod. If prod is already running this way, the shortcut just opens a
window on it and leaves it running when the window closes.

Check http://127.0.0.1:8100/api/health. Prod stops whenever the PC restarts or the window that started it closes.

---

## 3. Building the feature (in the DEV folder)

### Where things live
| You are changing | Edit here |
|---|---|
| A screen / page | `frontend/src/pages/` |
| A reusable UI piece | `frontend/src/components/` |
| Calls from UI to API | `frontend/src/api/client.ts` |
| An API endpoint | `backend/app/routers/` (register it in `backend/app/main.py`) |
| Business logic / queries | `backend/app/*.py` |
| Database tables / columns | `.cursor/db/*.sql` (see section 4) |
| Start/deploy scripts | `scripts/` |

Before changing a feature, read `AGENTS.md` and `docs/change-impact.md`: they list what else depends on each part.

### How your edits show up
- **Frontend edits** appear in the browser immediately (hot reload).
- **Backend edits are NOT reliably live.** On this machine the API auto-reload hangs while the chat connection is
  open, so the old code keeps running. After **every backend edit**, restart the API by hand:
  ```powershell
  # stop the dev API (port 8000) and everything under it
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match '8000' -and $_.CommandLine -notmatch 'multiprocessing' } | ForEach-Object { taskkill /PID $_.ProcessId /T /F }
  # start it again from the dev folder, in its own window
  .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
  ```
  Then confirm your change is live (open the new endpoint, or check http://127.0.0.1:8000/openapi.json for your new route).
  Do not close the Vite dev server or the desktop app.

### Commit often, in small pieces
```powershell
git add -A
git commit -m "Short, clear description of the change"
```
Run `git status` before committing. Make sure no stray files are listed (never commit `.env`, uploads, or PDFs).

### Test before you push (do all three)
1. **Use the feature in dev** (http://localhost:5173), including the unhappy paths.
2. **Type-check and build the frontend.** This catches errors the dev server hides and that would break the prod build:
   ```powershell
   cd frontend
   npx tsc -b
   npm run build
   cd ..
   ```
   Both must finish with no errors. (`npm run build` creates `frontend\dist`, which is git-ignored.) Then
   `npm run lint` (the linter: a hook called conditionally, a missing effect dependency, an `option` with no selected state, ...) and,
   after the build, `npm run check:bundle` (the app must still start without downloading every page). If you changed
   colours or anything in `frontend\src\theme`, also run `npm run check:themes` there: it checks that every theme is
   readable and that the Default theme still matches the stylesheet.
3. **Backend tests**, if you changed backend logic. One-time install, then run:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt -c backend\constraints.txt
   .\.venv\Scripts\python.exe -m pytest backend/tests
   .\.venv\Scripts\python.exe -m ruff check backend
   ```
   `ruff` (the Python linter) also runs inside `pytest` (`test_lint.py`). It looks for bugs, not style: an unused name, a repeated
   dictionary key, a `raise` outside a handler, a swallowed error. A failure you swallow **on purpose** says why on the same line:
   `except Exception:  # noqa: BLE001, S110 - never raise from a finaliser`.

Some tests drive the real endpoints against your **development** database and stay off unless you ask: set
`ORION_AUTH_DB_TESTS=1` (sessions and sign-in limits; makes and removes `zz_sec_*` users), `ORION_CHAT_DB_TESTS=1` (messaging) or
`ORION_DASHBOARD_DB_TESTS=1` (dashboards). Run the one you changed before you push; CI cannot.

### Linting, and why nothing is reformatted

`ruff` (Python, `ruff.toml`) and `oxlint` (the frontend, `frontend/.oxlintrc.json`) look for **bugs**; they never rewrite your code.
Formatters (`ruff format`, Prettier) are deliberately **not** enforced: they would rewrite most of the repository in one commit and
bury `git blame`. Format what you write; do not reformat what you did not change. `.editorconfig` sets indentation and the final newline
in your editor. To run the checks on every commit, once: `pip install pre-commit` then `pre-commit install` (optional; CI runs the
same ones). A rule you disagree with is changed in the config, in a pull request that says why, not switched off with a comment.

### Before you open a pull request

GitHub runs the same checks on every pull request (`.github/workflows/ci.yml`): the backend tests and lint on Windows, the
frontend lint, type-check, build, bundle-size and theme checks, and an audit of both sets of packages for known vulnerabilities. They need no database, so a
test that reaches for the development database passes on this PC and fails there; stub the database call (see the loop-check
tests in `test_history.py`). Open the pull request only when step 2 and 3 above pass here; a red run on the pull request means
the same thing as a red run here, so fix it before merging. **One-time GitHub setting** (repository owner): Settings > Branches >
add a rule for `main` > "Require a pull request before merging" and "Require status checks to pass" with `backend`, `frontend`
and `dependency-audit`. Without it, a red run does not stop a merge.

### Dependencies

Python packages are pinned: `backend/requirements.txt` lists the direct ones at exact versions, and `backend/constraints.txt` locks
every package they pull in, so prod installs exactly what was tested. Every install uses both
(`pip install -r backend/requirements.txt -c backend/constraints.txt`). Dependabot opens a pull request for an update; CI runs on it.

**Dependabot pull requests.** Once a week (monthly for GitHub Actions) Dependabot opens at most one pull request per kind:
the Python minor/patch group, the npm minor/patch group, and one for all the Actions. Handle them like this:
1. Merge only when all three checks are green. Take them one at a time, in this order: Actions, Python, npm.
2. After a merge, another may say it has a conflict, or its green checks may predate the merge. Comment `@dependabot rebase`
   on it, wait for its checks to run again, then merge. Do not resolve a Dependabot conflict by hand.
3. After merging the Python group, pull `main` and run the app on dev once: CI cannot exercise the AI providers or the backup upload.
4. A major upgrade (recharts, vite and plugin-react are held back on purpose, see `.github/dependabot.yml`) is a piece of work, not a
   click: do it in its own branch, then delete its `ignore` entry. Never merge one that is red.
Closing a pull request does not stop Dependabot reopening it; put the package in `ignore` instead.

To upgrade by hand: change the pin in `requirements.txt`, then in a **new, empty** virtualenv run
`pip install -r backend/requirements.txt` and `pip freeze`, and replace the package lines of `constraints.txt` with the result (keep
its three comment lines; do not freeze your everyday `.venv`, it holds tools that are not Orion's). Run the tests, and `pip-audit -r
backend/constraints.txt --disable-pip --no-deps`. Frontend packages are locked by `package-lock.json`; `deploy.ps1` uses `npm ci`.

**Why step 2 matters:** the production build is stricter and styled differently from the dev server.
A page can look fine in dev and break in prod (that already happened once). To see how it will look in prod:
```powershell
cd frontend; npm run build; npm run preview
```
and open the address it prints (the API must be running on port 8000).

---

### Trying the Copilot without a key

Most questions need no model: Orion answers "top 10 customers", "why did revenue fall", "delete client CL-0007", "remind me to ..." itself
from the real tools. For the open-ended ones, set `ORION_AI_LOCAL_PROVIDER=scripted` in your dev `.env` (never in prod) for a stand-in model, or install
Ollama and a small model (docs/ai-setup.md). Cloud keys are not needed for any of it. The routing tests are `backend/tests/test_ai_routing.py`;
`python scripts/ai_routing_report.py` rewrites docs/ai-routing-test-report.md.

## 4. If your feature changes the database

`deploy.ps1` applies the schema itself (`python -m app.migrate`) before it touches the running server, and a migration that
fails stops the deploy. It applies only the files listed in `entities.SQL_MIGRATIONS`, so a new `.sql` file that is not in that
list will never reach prod.

1. Write SQL that is safe to re-run and safe on a database that already has data:
   `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`.
   Prefer additive changes. Never drop or rename a column in the same release that stops using it.
2. Put it in `.cursor/db/`. Either extend an existing file the app already applies
   (`tally_ods_schema.sql`, `tally_dw_schema.sql`, `dw_schema.sql`, `migrate_bill.sql`,
   `migrate_case_transaction_bill.sql`, `migrate_opportunity_fields.sql`), or add `migrate_<name>.sql`.
3. For a **new** file: add its path to `SQL_MIGRATIONS` in `backend/app/entities.py`, and its filename to **both**
   `scripts/init_db_windows.ps1` and `scripts/init_db_mac.sh`. A test fails if these disagree.
4. Restart the dev API. It applies the SQL to the dev database `orion`. Restart it **again** to prove the SQL can
   run twice without errors. Check the API window for `Could not apply ...` messages, and run
   `python -m app.migrate --status` in `backend`: every step should say `applied`.
5. Never change the dev database by hand and forget to write the SQL file. Prod would not get the change.

The full checklist, including the prod backup step, is in `DEPLOYMENT.md` ("Checklist: adding a database change").

---

## 5. Sending your work to GitHub

```powershell
git push -u origin feature/short-name
```
Git prints a link ending in `/pull/new/feature/short-name`. Open it in your browser and:
1. Click **Create pull request**.
2. Read the **Files changed** tab. Check there is nothing you did not intend (secrets, big files, unrelated edits).
3. Click **Merge pull request**, then **Confirm merge**.

Then update your dev folder and clean up:
```powershell
git checkout main
git pull origin main
git branch -d feature/short-name
```

---

## 6. Releasing to PRODUCTION

Do this only after the pull request is merged into `main`.

### Step 1: Tag the release (a named, reversible version)
```powershell
cd F:\prakashSecurities-main\prakashSecurities-main
git checkout main
git pull origin main
git tag            # lists existing versions
git tag v1.0.1
git push origin v1.0.1
```
Version numbers: bug fix `v1.0.1` → `v1.0.2`; new feature `v1.1.0`; big change `v2.0.0`.
**One-time:** if `git tag` lists nothing, tag the version prod already runs first, so you have something to roll back to:
`git tag v1.0.0 67d4c35` then `git push origin v1.0.0`.

### Step 2: The database backup (automatic)
The deploy takes a safety dump of the prod database itself, into `C:\orion-backups`, checks that it reads back, and stops if
it cannot. You do not run anything. **Only the very first deploy of the new script is different:** the office PC still has the
old `deploy.ps1`, which takes no dump, so that once take one by hand:
```powershell
New-Item -ItemType Directory -Force C:\orion-backups | Out-Null
$env:PGPASSWORD = "<orion_user password from C:\orion-prod\.env>"
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -h localhost -U orion_user -d orion_prod -F c -f C:\orion-backups\orion_prod_before_v1.0.1.dump
```

### Step 3: Deploy
```powershell
cd C:\orion-prod
.\scripts\deploy.ps1 -Ref v1.0.1
```
It checks out that version, installs the packages, takes the dump, **applies the database schema (a failed migration stops here and
changes nothing)**, builds the web app on the side, then stops the old server, starts the new one in a new window and tests it. It
takes a few minutes and prod is down for a few seconds. It refuses to run if `C:\orion-prod\.env` is not `ORION_ENV=production` or
if prod has local edits.

**If you start prod with the Orion PROD desktop shortcut** rather than the script: close the PROD window, run
`.\scripts\deploy.ps1 -Ref v1.0.1 -NoRestart`, open prod with the shortcut, then run `.\scripts\deploy.ps1 -Verify` to test it.

### Step 4: Verify
The deploy already tested the new server (it prints each check, `ok` or `FAIL`). It ends with `Deployed v1.0.1`. Then:
1. Open http://127.0.0.1:8100, hard refresh with **Ctrl+Shift+R**, sign in, and use your new feature.
2. **Admin > System** should list nothing under "Needs attention". `http://127.0.0.1:8100/api/health/version` names the running commit.

### Step 5: If it fails, or if something is wrong afterwards
- **A deploy that prints `DEPLOY FAILED`** has already put the previous version back where it could (it says what), and names the safety
  dump. Read the line after `FAILED`, fix the cause, deploy again.
- **A release that deployed fine but is wrong:**
```powershell
cd C:\orion-prod
.\scripts\deploy.ps1 -Ref v1.0.0
```
This restores the old **code** (and is dumped and tested like any deploy). It does not undo a database change that already ran. If
the schema or data itself is the problem, restore the safety dump (ask for help with this; `docs/backup.md`).

---

## 7. Shutting down
1. Commit or push any unfinished work: `git add -A; git commit -m "WIP"; git push -u origin <your-branch>`.
   Uncommitted work survives a shutdown, but pushing makes a safe copy on GitHub.
2. Close the dev windows (API, Vite) or the desktop app.
3. Close the Orion PROD window (or the `start-prod.ps1` window). Prod is off until you start it again.
4. Leave PostgreSQL alone, it manages itself.

---

## 8. Quick command cheat sheet

| I want to... | Run (folder) |
|---|---|
| Start dev app | `.\scripts\start-desktop.ps1` or `.\scripts\start-modern.ps1` (dev folder) |
| Start prod | Orion PROD desktop shortcut, or `.\scripts\start-prod.ps1` (`C:\orion-prod`) |
| Sync with GitHub | `git checkout main; git pull origin main` (dev folder) |
| New feature branch | `git checkout -b feature/name` (dev folder) |
| See what I changed | `git status` and `git diff` (dev folder) |
| Save work | `git add -A; git commit -m "msg"` (dev folder) |
| Push for review | `git push -u origin feature/name` (dev folder) |
| Which branch am I on? | `git branch --show-current` |
| Release | tag, back up, close Orion PROD, `.\scripts\deploy.ps1 -Ref vX.Y.Z -NoRestart` (`C:\orion-prod`), reopen |
| Roll back | `.\scripts\deploy.ps1 -Ref vOLD` (`C:\orion-prod`) |

---

## 9. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `fatal: not a git repository` | You are in the outer folder. `cd` into the inner `prakashSecurities-main\prakashSecurities-main`. |
| My backend change does nothing in dev | API auto-reload hung. Restart the API by hand (section 3). |
| Dev works, prod looks different or broken | The production build differs from the dev server. Run `npx tsc -b` and `npm run build` in `frontend`, and preview with `npm run preview`. Also check `.gitignore` did not start ignoring a source folder: `git check-ignore -v --no-index <file>`. |
| `npm run build` fails with type errors | Fix them. The dev server does not type-check, but the prod build does. |
| `deploy.ps1` says ORION_ENV is not production | You ran it in the dev folder. Run it only in `C:\orion-prod`. |
| `deploy.ps1` says local changes | Someone edited files in prod. `cd C:\orion-prod; git restore .` then deploy again. |
| `Could not apply migrate_...` in the prod window | A database change did not apply. Check table ownership and that the SQL is wired at startup (section 4). |
| Prod will not start: `password authentication failed` | `ORION_DB_PASSWORD` in `C:\orion-prod\.env` must be the same as the dev `orion_user` password (they share the role). |
| Port already in use (5173 / 8000 / 8100) | An old server is still running. Close its window, or find it with `Get-NetTCPConnection -LocalPort 8100 -State Listen`. |
| Prod chat does not connect | `uvicorn[standard]` (WebSocket support) must be installed. `deploy.ps1` installs it from `backend/requirements.txt`. |
| Password-reset emails link to the wrong address | `ORION_APP_URL` in the prod `.env` is set to `https://desktop-e4tua9u.tail6be739.ts.net:8443`. That address only works after `tailscale serve --bg --https=8443 http://127.0.0.1:8100`. Until then set it to an address that does. |
| Orion PROD shortcut shows an error box | Read the message, then `C:\orion-prod\data\prod-desktop.log` (launcher) and `prod-server.log` (server). |
| Orion PROD shortcut does nothing, or has a blank icon | The shortcut points at files that do not exist. Recreate it: `cd C:\orion-prod; .\scripts\install-prod-desktop-app.ps1`. |
| Not sure what prod is running | `git -C C:\orion-prod log --oneline -1` |

---

## 10. Rules to keep prod safe
- Never edit files, or run SQL by hand, in prod. Everything goes dev → GitHub → deploy.
- Never commit secrets: `.env`, passwords, keys. `.env` is git-ignored, keep it that way.
- Never reuse a dev session secret or admin password in prod. The server enforces it: with `ORION_ENV=production` it will not start
  if the session secret (at least 32 characters) or database password is empty, a development or example value, and it will not
  create the first administrator with a default or short (under 12 characters) password. `deploy.ps1` runs the same check before it
  stops the running server (`python -m app.startup_checks`, from `backend`).
- Keep `ORION_DB_PASSWORD` identical in both `.env` files (dev and prod share the `orion_user` database role).
- Always merge through a pull request, never push straight to `main`.
- Always back up the prod database before a release that changes the schema.
- Tally data in prod is loaded from Tally itself; the dev copy is not synced.

---

## 11. Developing from a second PC

A second PC (for example a personal PC at home) is a **DEV-only** machine. It has its own clone, its own
PostgreSQL with its own `orion` database, and its own `.env`. PROD and Tally stay on the office PC.

| | Office PC | Second PC |
|---|---|---|
| DEV | `F:\prakashSecurities-main\prakashSecurities-main`, DB `orion` | its own clone, its own local DB `orion` |
| PROD | `C:\orion-prod`, DB `orion_prod` | **none**: no prod folder, no prod `.env`, no prod data |
| Tally | installed (port 9000) | not installed |

### One-time setup
```powershell
git clone https://github.com/shaileshmishraa/prakashSecuritiesOrion.git
cd prakashSecuritiesOrion
.\scripts\install-windows.ps1 -SkipDbInit     # add -SkipWinget if Python, Node and PostgreSQL are already installed
```
Then open `.env`, set `ORION_POSTGRES_SUPER_PASSWORD` to the password chosen when PostgreSQL was installed on
**this** PC, set new values for `ORION_DB_PASSWORD`, `ORION_SESSION_SECRET` and `ORION_ADMIN_PASSWORD`, and run:
```powershell
.\scripts\init_db_windows.ps1
```
This PC runs its own PostgreSQL server, so its `ORION_DB_PASSWORD` does not have to match the office one
(that rule only applies to dev and prod on the office PC, which share one server).

### Dev data
The new database has the tables but no business data, and nothing fills it automatically. Enter records
in the app, or bring a copy of the office dev data (it includes the loaded Tally tables): on the office PC run
`pg_dump -h localhost -U orion_user -d orion -F c -f orion_dev.dump`, copy the file over, and restore it here with
`pg_restore -h localhost -U postgres -d orion --clean --if-exists --no-owner orion_dev.dump`, then re-run
`.\scripts\init_db_windows.ps1` to reapply the grants.

Never copy `orion_prod` to a second PC.

### Tally
Screens that read the loaded Tally tables work from a restored dev dump. To test the live sync, set
`ORION_TALLY_HOST` in this PC's `.env` to the office PC's Tailscale IP. The office PC must be on with Tally
open, and its firewall must allow port 9000 from the tailnet.

### Switching between PCs
- **Before leaving a PC:** `git add -A; git commit -m "WIP"; git push -u origin <your-branch>`.
- **When sitting down at the other:** `git fetch; git checkout <your-branch>; git pull`, then restart the dev API.
  The restart applies any database change from the branch to that PC's `orion` (section 4).
- Database changes travel only as SQL files in git. A change made by hand on one PC never reaches the other.

### Releasing
Pull requests and tags can be made from either PC. `deploy.ps1` runs only on the office PC, in `C:\orion-prod`.
