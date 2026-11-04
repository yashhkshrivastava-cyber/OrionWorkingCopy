# Architecture

How Orion is put together. For what each feature does see [features.md](features.md); for what depends on what
see [change-impact.md](change-impact.md).

## The system in one picture

```
 Browser or desktop window
        |
        |  HTTP + one WebSocket (chat), session cookie
        v
 FastAPI (backend/app)  ------------------------------->  Tally Prime XML server
        |                    HTTP XML, port 9000           (office PC only)
        |  psycopg2, one short connection per request
        v
 PostgreSQL, one database, four schemas
   orion_ods   operational records, users, bills, chat      (written by the app)
   orion_dw    versioned warehouse of orion_ods              (loaded on demand)
   tally_ods   working copy of the Tally books               (loaded from Tally)
   tally_dw    versioned warehouse of tally_ods              (loaded on demand)
```

There is no queue, cache or background worker. Everything happens inside a request, including the warehouse
and Tally loads, which a user starts from the Data screens.

## Processes and ports

| | Dev | Prod |
|---|---|---|
| UI | Vite dev server, port 5173, proxies `/api` to the API | served by the API process from `frontend/dist` |
| API | uvicorn, port 8000, `--reload` | uvicorn, port 8100, no reload, `ORION_SERVE_FRONTEND=1` |
| Database | `orion` | `orion_prod`, same PostgreSQL server and same role `orion_user` |
| Folder | the dev clone | `C:\orion-prod`, changed only by `scripts/deploy.ps1` |

`desktop/app.py` (dev) and `desktop/prod_app.py` (prod) open the same site in a native window and start the
servers if they are down. They add no behaviour of their own.

## Backend

`backend/app/main.py` builds the app, applies the schema at startup (below) and registers the routers under `/api`.

- **Routers** (`routers/*.py`) are thin: validate input, check permission, call a module, turn its errors into
  HTTP responses. Each API area has one router file.
- **Modules** (`billing.py`, `entities.py`, `dw_sync.py`, `dashboard/`, `tally_*.py`, `chat.py`, `auth.py`, ...)
  hold the logic and the SQL. There is no ORM: queries are written by hand with psycopg2.
- **`database.py`** gives `get_connection()` and the `db_cursor(commit=...)` context manager. A function that must
  do several writes atomically opens one connection and commits once (see `billing.record_payment`).
- **`config.py`** loads `.env` from the repo root with `override=True`, so `.env` wins over the process
  environment. All settings are `ORION_*` variables; `.env.example` and `deploy/env.prod.example` list them.

### Schema at startup

`lifespan()` in `main.py` runs these in order, every time the API starts:

1. `ensure_user_profile_columns`, `ensure_chat_tables`, `ensure_signup_table` (statements inside the Python)
2. `migrate.apply_at_startup`: every file in `entities.SQL_MIGRATIONS` (the bill, revenue, opportunity, data-rule, security and
   idempotency files, the warehouse and both Tally schemas), each result recorded in `orion_ods.schema_migrations`
3. `ensure_default_admin`: creates the admin from `.env` only when there are no users at all

A failed step is recorded with its error. In production the API **refuses to start**; elsewhere it logs and carries on, and
`/api/health/ready` and the System page say the schema is not right. If the app's role does not own a table, the step retries as the
PostgreSQL superuser when `ORION_POSTGRES_SUPER_PASSWORD` is set.

`deploy.ps1` runs the same thing (`python -m app.migrate`) **before** it stops the old server, so a failed migration stops the deploy
with production untouched; the start-up run is the second chance. The same script takes a safety dump first and smoke-tests the new
server after (`deploy_tools.py`). See "Migrations and a deploy that checks itself" in features.md.

`schema.sql` (the base tables) and the early `migrate_app_user_*` files are **not** in the list. They run only from
`scripts/init_db_windows.ps1` and `scripts/init_db_mac.sh`, which run every `.sql` file in order.

## Database connections

The API borrows PostgreSQL connections from a pool (`db_pool.py`, used through `database.db_cursor()` / `get_connection()`), at most
`ORION_DB_POOL_MAX` (20) per process. `raw_connection()` and the few `psycopg2.connect` calls for other roles (the superuser helper,
the schema scripts) are not pooled. See "The database connection pool" in features.md.

## Logging and health

Every request passes `RequestContextMiddleware` first (a reference, a timer, the access line) and `ErrorBoundaryMiddleware` last
(an unhandled error becomes a 500 that names the reference). Logs go to the console and `data/logs/orion.log`. The admin System
page reads `/api/health/details`. See "Logs, health and the System page" in features.md.

## Authentication and permissions

- Sign-in creates a row in `orion_ods.app_session` and sets an HTTP-only cookie `orion_session` holding
  `<random id>:<expiry>:<hmac>`, signed with `ORION_SESSION_SECRET`. The server can end a session (sign-out, password change,
  disabled account, an admin, the person's device list), and a revoked cookie stops working at once (`sessions.py`).
  Failed sign-ins are rate-limited per name and address (`throttle.py`, `orion_ods.auth_attempt`).
- `dependencies.py` turns the cookie into the current user (`sessions.user_for_token`) and provides one dependency per permission.
- A user has a **role** (`admin`, `editor`, `viewer`) and a set of **access flags** (`auth.ACCESS_FLAGS`) in
  `orion_ods.app_user`. The role
  sets the defaults for the flags; an admin can change each flag per user. A write flag implies its read flag.

| Flag | Guards | Dependency |
|---|---|---|
| `ods_access` / `ods_write` | Operational Data | `require_ods` / `require_ods_write` |
| `dw_access` / `dw_write` | Orion warehouse browse / refresh | `require_dw` / `require_dw_write` |
| `tally_access` / `tally_write` | Tally working copy browse / load | `require_tally` / `require_tally_write` |
| `tally_dw_access` / `tally_dw_write` | Tally warehouse browse / load | `require_tally_dw` / `require_tally_dw_write` |
| `billing_access` / `billing_write` | Billing | `require_billing` / `require_billing_write` |
| `etl_access` / `etl_write` | ETL pipelines: see / run | `require_etl` / `require_etl_write` |
| `letterhead_access` / `letterhead_write` | Letterhead: read, print, stamp and the PDF tools / write letters | `require_letterhead` / `require_letterhead_write` |
| `documents_access` / `documents_write` | Document Center: open and download / upload, edit, delete, see Confidential | `require_documents` / `require_documents_write` |
| `bank_access` / `bank_write` | Bank: balance, ledger, Cash dashboard tab, Copilot bank tools / set up, enter, void, upload, match (admins only until given) | `require_bank` / `require_bank_write` |
| `tenders_access` / `tenders_write` | Tenders: see the GeM searches and bids / change searches, check GeM now, shortlist and dismiss | `require_tenders` / `require_tenders_write` |
| `attendance_access` / `attendance_write` | Attendance: see the registers / make, change and post them, save people who are not employees | `require_attendance` / `require_attendance_write` |
| `ai_access` | AI Copilot (it then does only what the person's other flags allow) | `require_ai` |
| `orion_dashboard_access` | Orion dashboards | `require_orion_dashboard` |
| `tally_dashboard_access` | Tally dashboards | `require_tally_dashboard` |
| role `admin` | User administration, reversing a bill payment, changing the letterhead, deleting a document for good | `require_admin` (the purge route checks the role itself) |

`/api/auth/me` returns the user with derived `can_*` booleans and a `pages` list. The frontend uses those to
show or hide navigation and buttons. That is convenience only: the dependency on the route is the control.

## The AI Copilot

```
 AI panel, palette, "Ask AI" buttons   (frontend/src/components/assistant, state in frontend/src/ai)
        |   POST /api/ai/chat  (server-sent events)          routers/ai_router.py
        v
 orchestrator.run_turn   gate (on? limits? one at a time?) -> routing.engine.run
        |
        |-- 1. rules recognise it (routing/intents) ........ Orion answers from the tools, no model        [path "app"]
        |-- 2. local model (providers/ollama_provider) ..... a trimmed tool list, answer checked, bounded retry   [path "local"]
        '-- 3. cloud model, only if routing/policy allows .. OpenAI / Anthropic, minimised and name-masked   [path "cloud"]
        v  a model asks for a tool
 tools/core.execute      exists? allowed for this person? arguments valid? -> run, or prepare + wait for confirmation
        |                everything audited (ai_audit); results returned as untrusted data
        v
 tools/{analytics,records,actions}   thin functions over the application's own services:
        dashboard engine (orion_dw), entity_service + entities (orion_ods), billing, receivables, documents, bank, forecast, mail, reports
```

- The only things that touch data are the tools, and each tool calls the same service code the screens use, so the same
  rules apply (an issued bill is not edited, a revenue entry that belongs to a bill is left alone, private columns are not
  returned). The AI layer (`backend/app/ai`) imports the application; the application does not import it, apart from the
  router, the startup schema step and the `ai_access` flag.
- Each answer is one request that stays open and streams events: `conversation`, `start`, `text`, `block`, `tool`, `ui`,
  `confirm`, `notice`, `sources`, `done`, `error`. The frontend (`api/client.ts` `aiApi.chat`) reads them and
  `ai/transcript.ts` turns them into a message made of parts. Closing the request (Stop) ends the loop and the server keeps
  what was written.
- Confirming is a separate, ordinary request (`/api/ai/actions/{id}/confirm`); the model is not involved and cannot confirm.
- Configuration is in `backend/app/ai/config.py`: the only place that names a model, a limit or a key. The chat screen, the tools and the
  business logic know nothing about which provider answered; they receive the same events either way (plus a `route` event naming who).
- Schema: `.cursor/db/migrate_ai.sql`, applied at startup with the other `orion_ods` files (`entities.AI_MIGRATE`).

## Frontend

A single-page React app (Vite, TypeScript, Tailwind 4, Recharts, React Router).

- **`App.tsx`** defines the top-level routes. `/login` and `/reset-password` stand alone; everything else is
  inside `Layout`.
- **`components/Layout.tsx`** is the shell. It draws one of two frames around the same pages: the classic one (the dark navigation rail, the top bar, the account menu, the phone
  drawer) or Lumen's (`components/lumen/`: a floating dock, a top bar with search and a + menu, a phone tab bar, a launcher), by the person's `experience` setting. The areas
  and who sees them are the `NAV_GROUPS` list in `components/nav/navigation.ts`, shared by both.
- **`components/WorkspacePanes.tsx`** keeps the five workspaces (dashboard, data, utility, admin, messages)
  mounted once visited and hides the inactive ones, so switching back is instant and keeps scroll, filters and
  form state. Their routes are in **`workspaceRoutes.tsx`**, and every page there is loaded on demand with `lazyPage` (see "Shell and navigation" in features.md). A page inside a workspace is therefore not
  unmounted when the user navigates away: do not rely on unmount to reset state.
- **`context/`**: `AuthContext` (current user), `AppearanceContext` (the theme system's state; `ThemeContext` is its
  light/dark view for older code),
  `ChatContext` (WebSocket and unread counts), `TasksContext` (the task bell and rail numbers, asked again every minute), `TabMemoryContext` (last address per rail item),
  `DataRefreshContext` (the top-bar refresh button bumps a `generation` number that data-loading effects
  depend on).
- **`api/client.ts`** is the only place that calls the API; **`types.ts`** types every response. All requests
  send the cookie.
- **`index.css`** holds the design system: the Default theme as CSS variables, their Tailwind names, base styles,
  shared classes (`.panel`, `.btn-primary`, the type scale `.t-*`) and the motion. Components use the tokens
  (`bg-surface`, `text-accent`, `bg-primary`, `brand-*`, `alt-*`, `.panel`) and never a colour of their own.
- **`theme/`** is the theme engine. A theme is data (`themes.ts`); `engine.resolveAppearance(prefs, mode)` is a pure
  function that returns one flat map of CSS variables; `apply.ts` writes it on `<html>` and caches it so the next visit
  paints in the right theme from the first frame (`public/theme-boot.js`, loaded by `index.html`, replays the cache). Because everything reads variables,
  a theme change re-skins the application without re-rendering it. `npm run check:themes` proves every theme is readable
  and that Default still equals the stylesheet. The settings are saved on the user (`app_user.appearance`) and on the
  device.

## Data flow

**Orion operational data.** Users enter records in Operational Data (generic forms driven by
`backend/app/entities.py`) or upload Excel. Bills are entered in Billing. All of it lands in `orion_ods`.

**Orion warehouse.** `dw_sync.py` copies `orion_ods` into `orion_dw` as SCD Type 2: a changed row closes its
current version and adds a new one, a deleted row is marked expired. A user runs it from Data > Orion >
Refresh the warehouse, or the hourly loader does it. **The Orion dashboards read `orion_dw`**
(`backend/app/dashboard/`), so their figures are as fresh as the last warehouse load, and a bill raised a minute ago
shows on them after the next load. The case-linked facts carry the case, client, capability and domain *as they were on
the day of the event* (point-in-time surrogate keys), which the dashboards use. Only the live version of each row is
read (`is_current` and not `is_expired`).

**Tally.** `tally_client.py` asks Tally Prime's XML server for masters and vouchers. `tally_ods.py` writes them
into `tally_ods` (SCD Type 1: latest value wins). `tally_dw.py` builds `tally_dw` from `tally_ods` (SCD Type 2).
**Tally dashboards read `tally_dw`**, so they show data only as fresh as the last Tally load and warehouse load.
Tally runs only on the office PC; elsewhere the Tally screens load but have nothing to show.

## Files on disk

`data/` (git-ignored, one per clone) holds uploads and logs: `avatars/`, `chat-media/`, `support/` (a copy of
each "Raise a request"), `mail/` (outgoing mail written to a file when SMTP is not configured), and the desktop
launcher logs. It is not in the database and is not covered by `pg_dump`.
