# Development vs. production

> New here? Start with **[DEVELOPMENT.md](DEVELOPMENT.md)**, the step-by-step guide from power-on to a live release.

Dev and prod run on the same Windows PC, in **separate folders, databases, ports and secrets**.
Code reaches prod only through GitHub.

| | Dev | Prod |
|---|---|---|
| Folder | `F:\prakashSecurities-main\prakashSecurities-main` | `C:\orion-prod` (a clone of GitHub) |
| Code | feature branches | `main` or a release tag, never edited by hand |
| Database | current dev DB / role | database `orion_prod`, same role `orion_user` |
| Ports | API 8000, Vite 5173 | one process on 8100 (UI + API) |
| Run with | Orion shortcut or `scripts\start-modern.ps1` (`--reload`) | Orion PROD shortcut or `scripts\start-prod.ps1` (no reload) |
| `.env` | dev values | `deploy\env.prod.example`, all secrets different |

## Daily workflow (in the dev folder)

```bash
git checkout main && git pull
git checkout -b feature/short-name      # or fix/short-name
# ...develop and test locally...
git add -A && git commit -m "Describe the change"
git push -u origin feature/short-name
```

Open a Pull Request into `main` on GitHub, review the diff, merge. Never commit straight to `main`.

## Releasing

After merging to `main`, tag the release and deploy it:

```bash
git checkout main && git pull
git tag v1.0.1 && git push origin v1.0.1
```

Then in PowerShell:

```powershell
cd C:\orion-prod
.\scripts\deploy.ps1 -Ref v1.0.1
```

`deploy.ps1` refuses to run unless `.env` says `ORION_ENV=production`, and refuses if the prod folder has local edits. In this
order, with the running server serving until step 6:

1. remembers the version that is running now (the way back);
2. checks out the new one (if `deploy.ps1` itself changed in it, it carries on with the new copy and says so);
3. installs the pinned packages (`backend/constraints.txt`), then **takes a safety dump of the production database** into
   `C:\orion-backups` and reads it back to prove it is whole. If it cannot, the deploy stops, nothing has changed;
4. checks that `.env` holds private secrets (below), then **applies the database schema** (`python -m app.migrate`). A migration
   that fails **stops the deploy here**, with the old server still running and the old code checked out again;
5. builds the web app into a side folder and swaps it in (the previous one is kept as `frontend\dist.previous`);
6. stops the old server, starts the new one in a new window, and **smoke-tests it**: it answers, the database and schema are ready, it
   is the *new* commit (not the old server still holding the port), the web app and its script load, security headers are on, an API
   page answers;
7. if the smoke test fails, **it puts the previous version back** (code, web app, packages), restarts it, checks it and exits with an
   error, printing the safety dump's path.

It ends by writing `data\release.json` (what runs, what ran before, when), which `/api/health/version` also reports.

| Switch | Use |
|---|---|
| `-Ref <tag>` | the version to deploy (default `origin/main`) |
| `-NoRestart` | do everything except stop and start the server (for the desktop shortcut; then run `-Verify`) |
| `-Verify` | after the shortcut started the server: smoke-test it against this folder's version and write the release record. Changes nothing |
| `-SkipBackup` | emergencies only: no safety dump |
| `-BackupDir`, `-KeepBackups` | where the dumps go (`C:\orion-backups`) and how many to keep (5; older ones are removed) |
| `-SmokeSeconds` | how long to wait for the new server to answer (120) |

**If a deploy fails** it says why, in red, after the words `DEPLOY FAILED`, then what was put back and where the safety dump is. Fix
the cause and run the same command again. A failed migration is listed, with its error, by `python -m app.migrate --status` (in
`C:\orion-prod\backend`, venv active); fixing the SQL and deploying again re-applies it.

**Rollback by hand:** `.\scripts\deploy.ps1 -Ref v1.0.0` (any earlier tag). It is the same deploy, so it is dumped, checked and tested
too. A rollback is code only. If a release damaged *data*, restore the safety dump (`docs/backup.md`, "Restoring": a safety dump is a plain `pg_dump -F c`, unencrypted, so `pg_restore` reads it directly).

**First deploy of this new script:** the copy of `deploy.ps1` on the office PC is the old one until it checks out the release that
holds the new one, so that one deploy runs the old steps. Take a manual dump first (the command in DEVELOPMENT.md, section 6), then
deploy as usual. Every deploy after it is the new flow.

## The database schema and `python -m app.migrate`

Every file listed in `entities.SQL_MIGRATIONS` is applied in order and recorded in `orion_ods.schema_migrations` (name, checksum,
status, when, how long, the error if it failed). A file is applied when it is new or its text changed since it last applied, and
skipped otherwise. The three warehouse schemas (`dw_schema.sql`, `tally_ods_schema.sql`, `tally_dw_schema.sql`) are re-run every time
because the loads depend on them being current. The deploy runs it before the server is touched, and the API runs it again at start.

- `python -m app.migrate --status` shows every step and its state. `--force` re-applies every file.
- In **production** the API refuses to start when a step failed. Elsewhere it logs the failure and keeps going, and
  `/api/health/ready` answers 503 `{"status":"degraded", ...}` and **Admin > System** lists "Database schema" under "Needs attention".
- A step that needs the table owner (an `ALTER` on a table `orion_user` does not own) is retried as the PostgreSQL superuser if
  `ORION_POSTGRES_SUPER_PASSWORD` is in `.env`. Without it the error says so, in words.
- A failed row for a file the **running** code does not know is ignored: that is what a rolled-back release leaves behind.

## Production refuses development secrets

The code falls back to published development values (session secret, database password, first admin password) so a fresh
checkout runs with no setup. In production that would let anyone who has read the repository sign a cookie for any user, so with
`ORION_ENV=production` the API stops at startup, before touching the database, if:

- `ORION_SESSION_SECRET` is empty, shorter than 32 characters, or a development/example value (`change-me...`, `your-...`);
- `ORION_DB_PASSWORD` is empty or a development/example value;
- there is no user yet and `ORION_ADMIN_PASSWORD` is empty, a development/example value, or shorter than 12 characters.

The message lists every problem. `deploy.ps1` runs the same check (`cd backend; python -m app.startup_checks`) after installing
packages and before stopping the running server, so a bad `.env` fails the deploy and leaves the current server up. If you
see this at the next deploy, fix `C:\orion-prod\.env`; a secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Changing `ORION_SESSION_SECRET` signs everyone out (their cookies no longer verify), which is the point after a leak.

## Saving a bill or a payment twice

Creating a bill, editing one and recording a payment now carry a one-time key (`Idempotency-Key`), so a double-click or a retry saves
once. A browser tab that was open **before** this deploy still sends no key until it is reloaded; its saves work as before but are not
protected, and the log says so (`arrived without an Idempotency-Key`). Ask people to reload Orion after the deploy. After a week of no
such log lines, set `ORION_IDEMPOTENCY_REQUIRED=1` in prod's `.env` and restart to refuse unprotected saves (a person with a very old
tab then sees "This page is out of date. Reload it and try again"). If someone sees "This form was already used to save something
else", their earlier save went through: tell them to check the bill list before saving again.

## Pages load when they are opened (the release that split the web app)

Orion now downloads each page the first time someone opens it, and keeps its libraries in the browser's cache between releases. Two
things to know after the first deploy of this: a browser tab that was open **before** the deploy may show "Orion was updated ... Reload"
the first time someone opens a page they had not visited in it (the old file is gone); one click on Reload fixes it, nothing saved is lost,
so tell people to reload Orion once. And the first visit after each release downloads only the files that changed, so it is lighter than
before, not heavier. If a page ever stays on "Loading…" or a tab says "updated" after a reload, the build in
`C:\orion-prod\frontend\dist` is incomplete: rerun `.\scripts\deploy.ps1 -Ref <tag>`.

## Bill numbers open in a new tab (the release that added them)

A bill number is a link, with a card on hover, and a few other links now open in a new tab. In a browser that works at once. In the **Orion PROD
desktop window** it needs the window to be started *after* the deploy: that window's launcher (`desktop/prod_app.py`) is what offers "open a
second window", so a window that was already open keeps the old launcher, and its new-tab links would open the system browser (where you are not
signed in) until it is closed and opened again. The deploy asks you to close the PROD window anyway (`-NoRestart`); just open it again from the
shortcut afterwards. People on a browser need nothing but a reload.

## GST paid in instalments (the release that added them)

The deploy applies `migrate_bill_gst.sql` itself: a table of GST payments, and a running total on each bill. Bills already ticked as GST paid are
converted into the payments that tick meant (all the CGST and SGST, by whoever ticked it, when), so nothing changes for them except that the day
they were paid is shown as "not recorded". Two things to know afterwards. **The dashboards' GST figures** ("GST to pay", the Paid / Not paid split)
read the warehouse, which gets the new `gst_paid_amount` column at the next Orion warehouse load (it runs on its schedule; or run the Orion load on the ETL page):
until then bills with part-paid GST are still counted as owing all of it. And **a bill with GST paid cannot be cancelled** until its GST payments
are reversed (Payments, beside the GST status on the bill).

## The Bank (the release that added it)

The deploy applies `migrate_bank.sql` itself (its tables and the two views), and the API adds the two access flags at start. Three things to know.
**Only admins can see the Bank at first**: the first start gives `bank_access` and `bank_write` to admins and nobody else, and each other person is
given them in Admin (the balance of the firm's account is not something to show by default). **Nothing is in it until the opening balance is
entered**: an admin opens Utilities > Bank > Account and types what the bank held on a day (the balance is worked out from there, so choose a day
you have a bank statement for); until then the Bank pages, the Cash dashboard tab and the Copilot say the account is not set up. And **nothing
else changes**: the warehouse, the ETL pipelines, the bills and the dashboards' existing figures are untouched, and the backup already carries the
Bank's tables (they are in `orion_ods`). Rolling the release back leaves the Bank's tables in place and unused, which is harmless.

## The SQL editor (Data > SQL editor)

Administrators can run SQL against the database from the browser (see docs/features.md, "SQL editor"). **On production it is read-only by default**: it can read every table except the private ones (passwords, sessions, messages) and
nothing can be changed from it. To allow changes (data changes on tables Orion does not own, and views and tables in the `reports` schema) put `ORION_SQL_EDITOR=full` in that machine's `.env` and restart; `ORION_SQL_EDITOR=off` removes the page.
Every run is recorded in `orion_ods.sql_query_log`. The release that added it creates the schema `reports` and the two tables on its own (`app.migrate`); the database user must be allowed to create schemas in its own database, which `orion_user` is.

## Google Drive (the Document Center)

The Document Center can show a Google Drive next to Orion's own folders: browse it, copy or move documents both ways, and save a bill's PDF to it
(Utilities > Documents > Google Drive; a tick on each bill; company settings under "Drive settings", admins only).

**Without credentials** the feature runs against a **stand-in Drive** kept in `data/fake-drive` on that computer, so it can be tried. It looks and
works like Drive, nothing goes to Google, and the screen says so. **Production refuses it**: with no credentials, production shows "Google Drive is not
set up here" (`startup_checks.py` also rejects `ORION_GDRIVE=fake`).

**To switch to the real Google Drive** (nothing else changes; the same screens then work on the company's Drive):

1. In the [Google Cloud console](https://console.cloud.google.com/) make (or pick) a project for Orion. *APIs and services > Library*: enable the **Google Drive API**.
2. *APIs and services > OAuth consent screen*: for a Google Workspace company choose **Internal** (no Google review; only your own domain can sign in).
   With a personal Gmail choose **External** and leave it in **Testing**, adding the account that will connect as a test user.
   Add the scope `https://www.googleapis.com/auth/drive` (browsing folders that already exist needs it).
3. *Credentials > Create credentials > OAuth client ID*, type **Web application**. Under **Authorised redirect URIs** add
   `<ORION_APP_URL>/api/gdrive/callback` for each address Orion is reached at: `http://localhost:5173/api/gdrive/callback` on a development computer and
   `https://<the Tailscale address>:8443/api/gdrive/callback` on the office PC (the same address as `ORION_APP_URL`; it must match exactly).
4. Put the **Client ID** and **Client secret** in that computer's `.env` as `ORION_GOOGLE_CLIENT_ID` and `ORION_GOOGLE_CLIENT_SECRET`, and restart the API
   (`deploy.ps1` does this on prod). Nothing is committed: the `.env` is never in git.
5. An admin opens Documents > Google Drive and presses **Connect Google Drive**, signs in on Google's own page and allows Orion. Orion keeps only the
   refresh token, encrypted with a key made from `ORION_SESSION_SECRET` (changing that secret means connecting again). **Disconnect** is in Drive settings.

Notes. A connection made in the stand-in mode is forgotten when Google's credentials are added (file ids of one Drive mean nothing to the other): connect again;
nothing in either Drive or Orion is lost. A Google Docs / Sheets file is exported as PDF / Excel when copied into Orion. Nothing is ever deleted for good
from Drive by Orion (a move puts the original in Drive's trash, which Google empties after 30 days). No Google host is added to the Content-Security-Policy: the
server does all the talking to Google, and the browser is only sent to Google's sign-in page and back.

## Database connections

The API keeps up to 20 database connections open and lends them to requests (`ORION_DB_POOL_MAX`, `ORION_DB_POOL_TIMEOUT`). PostgreSQL on this
PC allows 100, and the dev and prod APIs each have a pool, so leave the maximum at 20 or lower. **Admin > System** shows how many are busy; if it
says requests "gave up waiting for a database connection", something is holding connections (look at the slow requests under it) before you
raise the maximum. After PostgreSQL is restarted nothing needs doing: the pool replaces dead connections on the next request. A busy server
answers people with "The server is busy right now. Try again in a few seconds." (503), not an error.

## Reading the logs and the System page

- **Admin > System** is the first place to look: it says whether the database answers, when each warehouse load and the backup last
  worked, how many requests failed or were slow since the server started, and the last warnings and errors. Anything it lists
  under "Needs attention" is worth reading before you ask anyone.
- **The log file** is `C:\orion-prod\data\logs\orion.log` (10 MB, ten files kept; `orion.log.1` is the previous one). To watch it:
  `Get-Content C:\orion-prod\data\logs\orion.log -Tail 100 -Wait`. A person who sees "Something went wrong ... reference
  3f9a8c1d22b04e77" gives you that reference: `Select-String 3f9a8c1d22b04e77 C:\orion-prod\data\logs\orion.log*` finds every line
  of that request, with the traceback.
- After a deploy, check `http://127.0.0.1:8100/api/health/ready` (it should say the database is ok) and the System tab.
- Settings (all optional, in `.env`): `ORION_LOG_LEVEL` (INFO; DEBUG shows health checks and assets), `ORION_SLOW_REQUEST_MS` (2000),
  `ORION_LOG_DIR`, `ORION_LOG_FILE=0`, `ORION_ACCESS_LOG=0`. The log never contains a password, a token or a query string.

## Browser security headers and the Secure cookie

Every response now carries a Content-Security-Policy and the other headers listed in `docs/features.md`. After the first deploy
of this, open prod in a browser and click through: Orion data, a dashboard, Billing (open a bill's PDF), Messages, Letterhead,
Documents. If anything is blank or missing, the browser console says `Refused to ...`; set `ORION_CSP=report-only` in prod's
`.env` and restart to keep the app working while you find what to allow, or `off` in an emergency (the other headers stay).

The session cookie is marked Secure only when the browser reached the server over HTTPS. Over the Tailscale HTTPS address that
is automatic if the proxy tells the server it is HTTPS (check once: sign in on the HTTPS address, then in the browser's developer
tools > Application > Cookies, `orion_session` should show Secure). If it does not, set `ORION_COOKIE_SECURE=1` in prod's `.env`;
that also blocks sign-in over any plain `http://` address except this PC's own (`127.0.0.1`/`localhost`, which the Orion PROD
window uses). Tell people to use the HTTPS address first.

## Calls and voice notes in Messages (the release that added them)

Browsers give the microphone, camera and screen only to a secure address, so calls and voice notes work on the Tailscale HTTPS
address (and on `localhost`), and say so on a plain `http://` one. After the first deploy: sign in on the HTTPS address as two people
(two browsers or devices), call one from the other, answer, turn the camera on and off, share a screen, hang up, and look for the
"Video call" line in the chat. Over Tailscale the two devices reach each other directly and nothing else is needed. For someone outside
it (mobile data), set `ORION_CALL_STUN_URLS` and, if that is still not enough, a relay with `ORION_CALL_TURN_URLS`,
`ORION_CALL_TURN_USER` and `ORION_CALL_TURN_PASSWORD` in prod's `.env` (a relay is a separate program such as coturn; the login is given to every
signed-in browser, which needs it to call). The schema gains `chat_call` and two columns, applied at start as usual. Ringing calls live
in the API process, so a restart during a call ends it.

## Sessions and sign-in limits (one-time effects of the release that added them)

- **Everyone signs in once.** Cookies made before server-side sessions existed carry no session row, so they are refused. Nothing
  to do; warn people.
- **Check the log after the deploy** for `Could not apply migrate_auth_security.sql`. If that table is missing nobody can sign in
  (sign-in needs it to record the session). The cause is the usual one: table ownership (see step 8 of the checklist below).
- A person who locks themselves out by mistyping waits up to 15 minutes; it ends by itself. The `auth_attempt` table is the record
  of who failed to sign in, from where and when (30 days). Do not clear it by hand in prod.

## Checklist: adding a database change

`deploy.ps1` applies the schema itself (`python -m app.migrate`), but only the files in `entities.SQL_MIGRATIONS`. A new
`.cursor/db/migrate_*.sql` file that is not in that list will never run in prod.

1. **Write the SQL so it is safe to re-run and safe on a database that already has data.**
   Use `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`.
   Prefer additive changes. Avoid dropping or renaming columns in the same release that stops using them.
2. **Put it in `.cursor/db/`.** Either extend an existing file that the app already applies
   (`tally_ods_schema.sql`, `tally_dw_schema.sql`, `dw_schema.sql`, `migrate_bill.sql`,
   `migrate_case_transaction_bill.sql`, `migrate_opportunity_fields.sql`), or add a new `migrate_<name>.sql`.
3. **If it is a new file, register it.** Add its path to `SQL_MIGRATIONS` in `backend/app/entities.py` (after the files it
   depends on), and its filename to **both** `scripts/init_db_windows.ps1` and `scripts/init_db_mac.sh` so a fresh database gets it.
   A test (`test_migrate.py`, `test_contracts.py`) fails if the list and the init scripts disagree.
4. **Test on dev.** Restart the dev API (it applies the SQL to `orion`), then use the feature. Restart it a
   second time to prove the SQL is re-runnable without errors, and run `python -m app.migrate --status` (in `backend`): every step
   says `applied`.
5. **Merge to `main`** through a pull request as usual.
6. **Deploy:** `.\scripts\deploy.ps1 -Ref <tag>`. The safety dump (step 3 of the deploy), the migration (step 4) and the
   post-deploy test (step 6) are part of it; there is nothing to run by hand.
7. **If the deploy stopped at the migration**, production is as it was. Read the error it printed (or `--status`), fix the SQL,
   merge, tag again and deploy. A common cause is table ownership: prod tables must be owned by `orion_user`, or
   `ORION_POSTGRES_SUPER_PASSWORD` must be in `.env` so the runner can retry as the owner.
8. **Verify** in the app or with `psql` that the new table or column exists in `orion_prod`.

A rollback does not undo a migration: the old code runs on the new schema because migrations are additive. If a migration
itself damaged data, restore the safety dump named at the end of the failed deploy.

## One-time production setup

1. Clone: `git clone https://github.com/shaileshmishraa/prakashSecuritiesOrion.git C:\orion-prod`
2. Create `C:\orion-prod\.env` from `deploy\env.prod.example` and fill in **new** secrets
   (`ORION_SESSION_SECRET`, DB password, admin password). Keep `ORION_ENV=production`.
3. Create the prod database (uses `ORION_DB_NAME`/`ORION_DB_USER` from the prod `.env`; the role must be `orion_user` and `ORION_DB_PASSWORD` must match the dev role's password):
   `cd C:\orion-prod; .\scripts\init_db_windows.ps1`
4. First deploy: `.\scripts\deploy.ps1` (builds everything and starts the server).
5. Check `http://127.0.0.1:8100/api/health`, then sign in with the prod admin account.
6. Optional, to reach prod over Tailscale on its own HTTPS port (dev's `tailscale-serve.ps1` uses 443 -> 5173):
   `tailscale serve --bg --https=8443 http://127.0.0.1:8100`, then set `ORION_APP_URL` to that address.

7. Install the desktop shortcut: `cd C:\orion-prod; .\scripts\install-prod-desktop-app.ps1`.
   It installs the window helper into the prod virtualenv and puts **Orion PROD** on the Desktop.

8. The AI Copilot works with no setting at all (Orion answers common questions itself). Optional: install Ollama on this PC and name a model
   (`ORION_AI_LOCAL_MODEL=...`) for open-ended questions: see docs/ai-setup.md. Cloud AI is off unless you also set
   `ORION_AI_CLOUD_ESCALATION=1`, a provider key (an API key made for the company, not a personal subscription), a model and a budget, and an
   administrator picks a policy other than *Local only*. Leave `ORION_AI_LOCAL_PROVIDER` at `ollama` or `none`: `scripted` is refused in production.

To start prod after a reboot without deploying: double-click **Orion PROD**, or run `.\scripts\start-prod.ps1`.

## The Orion PROD desktop shortcut

`desktop\prod_app.py` is the production twin of the dev app (`desktop\app.py`):

- Starts PostgreSQL if it is stopped, then the prod server (hidden, no console window) if it is not running.
- Opens prod in its own window. Every launch asks you to sign in again.
- Closing the window stops the server it started. A server that was already running
  (`start-prod.ps1`) is left alone.
- A second double-click brings the open window forward instead of starting another one.
- A download (an Excel export, a bill PDF) opens a Save As dialog that starts in the Downloads folder.
- Refuses to run in a folder whose `.env` is not `ORION_ENV=production`.

Logs are in `C:\orion-prod\data\`: `prod-desktop.log` (the launcher) and `prod-server.log` (the server).

When deploying, close the Orion PROD window first and use `.\scripts\deploy.ps1 -Ref <tag> -NoRestart`,
then open the shortcut again. Without `-NoRestart` the deploy starts prod in a console window instead.

The shortcut points only at files inside `C:\orion-prod`. Do not move the launcher or its icon under
`AppData`: files written there by a Microsoft Store app are invisible to Explorer, which makes the
shortcut do nothing and show a blank icon.

## Rules of thumb

- Never run `deploy.ps1` or `start-prod.ps1` in the dev folder, and never edit files in `C:\orion-prod`.
- Never reuse a dev password or session secret in prod. `init_db_windows.ps1` resets the password
  of the role in `ORION_DB_USER`. Prod shares the `orion_user` role with dev (the SQL hard-codes it),
  so keep `ORION_DB_PASSWORD` identical in both `.env` files or one environment will lose access.
- `data/` (uploads, mail, avatars) is not in git. Prod has its own `data/` in its own folder.
- Back up the prod database before a release that changes the schema:
  `pg_dump -U orion_user -d orion_prod -F c -f backup.dump`
