# Orion: guide for AI coding agents

Orion is the internal workspace of Prakash Securities, a security and manpower services company. It holds the
company's operational records, dashboards over them, a tax-invoice (billing) tool, a copy of the Tally books, and
team chat. It is a FastAPI backend, a React frontend and one PostgreSQL database, run on a single Windows PC.

Read this file first. It is short on purpose; the detail lives in `docs/`.

## Where to look

| You need | Read |
|---|---|
| How the pieces fit: processes, schemas, data flow, auth | [docs/architecture.md](docs/architecture.md) |
| What each feature does, its files, tables and rules | [docs/features.md](docs/features.md) |
| **What else breaks when you change something** | [docs/change-impact.md](docs/change-impact.md) |
| How money is added and taken away (bills, payments, GST, expenses, the bank), with diagrams and a review of gaps | [docs/money-flow.md](docs/money-flow.md) |
| Tables and columns | [.cursor/db/data-model.md](.cursor/db/data-model.md), and the two `tally_*_data_model.md` files beside it |
| Database backups: setup, keys, restore | [docs/backup.md](docs/backup.md) |
| Day-to-day workflow: branch, test, PR, release | [DEVELOPMENT.md](DEVELOPMENT.md) |
| Dev vs prod, deploy, rollback | [DEPLOYMENT.md](DEPLOYMENT.md) |

## Layout

```
backend/app/            FastAPI app
  main.py               app, startup schema steps, router registration
  routers/              one file per API area; thin, permission-checked
  entities.py           the entity registry: drives the generic data forms
  billing.py            bills, versions, payments, bill revenue entries
  letterhead*.py        the company letterhead, letters typed on it, PDFs put on it
  pdf_tools.py          the PDF tools (merge, split, rotate, compress, lock...): bytes in, bytes out, nothing stored; routers/pdf_tools_router.py; request_limits.py is the upload size guard
  documents.py          the Document Center: documents by company, case and client, versions, folders, expiry
  documents_filing.py   files bills, employee papers and EMD papers in the Document Center by themselves (the only writer of filed documents, their folders and placements, and of where a person chose to keep one: `document_filing_choice`)
  gdrive.py / gdrive_client.py  Google Drive in the Document Center: the connection, browsing, copies to and from Orion, bills saved to Drive; and the only code that talks to a Drive (a stand-in for development, Google's when its credentials are in the .env)
  documents_explorer.py the Document Center as a file explorer: places, browsing, moving (reads; writes go through documents.py and documents_filing.py)
  tasks.py, task_*.py   the task workspace: projects, tasks, reviews (tasks.py); comments, checklist, links, time (task_items.py); files (task_files.py); inbox (task_notify.py); personal to-do lists (task_todo.py); sprints; templates and repeating tasks; board, reports, search (task_views.py); the shared rules (task_common.py). Each table has one writer
  attendance.py         attendance registers (a case and a month): what posting one enters as salary lines and expenses, and taking it back (the only writer of attendance_* and of the lines it enters)
  opportunity_followups.py  the notifications to create a case and record an EMD once an opportunity is won (the only writer of opportunity_followup)
  emd_documents.py      the files kept against an EMD (receipt, instrument, refund papers); Contact and EMD themselves are generic entities
  forecast.py           the forecasting engine behind the Forecast tabs (pure Python, no dependency); dashboard/forecasting.py and tally_forecast.py feed it
  payroll.py            salary pay runs: a month's salary lines paid by one transfer (the only writer of salary_run, and of a line's paid state)
  payables.py           what is owed on expenses and the payments that settle them (the only writer of expense_payment)
  credit_notes.py       credit notes and bad-debt write-offs against a bill: made, approved by another person or an admin, reversed (the only writer of credit_note; billing.py moves the bill)
  cases.py, employees.py, user_overview.py   the case, employee and account pages (read only; money for billing, pay for bank, never the private employee columns)
  clients.py            a client's page and the client directory (read only: clients, cases and contacts, and for billing what was billed and what is owed, from receivables.py and billing.py)
  chat_groups.py        group chats: making one, who is in it and who runs it (the only writer of chat_member); chat.py holds everything else about a conversation, direct or group
  calls.py              voice and video calls between the two people of a chat: ringing, who answered, passing the browsers' connection set-up over the chat socket, the line a call leaves (the only writer of chat_call; the sound and picture never touch the server)
  tds.py                the TDS clients held back from payments: the ledger by year and the Form 26AS tick (the deductions themselves are written by billing.py)
  bank*.py              the bank account: balance, ledger, forecast, entries (bank.py), reading statements (bank_statement.py), matching them (bank_match.py)
  tenders.py            tender searches on GeM and MP Tenders: the check, matching, the schedule (the only writer of tender_*); gem_client.py and mptenders_client.py are the only code that talks to each portal
  dashboard/            Orion dashboards (read orion_dw: engine, views, insights, drill-through records)
  dw_sync.py            Orion warehouse load (orion_ods -> orion_dw)
  tally_*.py            Tally: XML client, working copy, warehouse, dashboard
  auth.py               users, sessions, roles and access flags
  ai/                   the AI Copilot: routing/ (rules, local-first engine, cloud policy), providers/, orchestrator, tool registry (tools/), insights, audit store
  entity_service.py     record create/change/delete rules shared by the record forms and the Copilot
  migrate.py            applies and records the schema files (entities.SQL_MIGRATIONS); `python -m app.migrate --status`
  deploy_tools.py       what deploy.ps1 calls: safety dump, smoke test, release record; /api/health/version
backend/tests/          unit tests and contract tests (no database needed)
frontend/src/           React app
  components/Layout.tsx       the shell: navigation rail, top bar
  workspaceRoutes.tsx         every workspace route (pages are lazy: lazyPage.tsx)
  api/client.ts, types.ts     the only place the API is called, and its types
  components/calls/           calls: the lazy host, the call engine (WebRTC), the call screen
  ai/, components/assistant/  the Copilot: conversation state, then its panel, blocks, palette and settings
  pages/, components/         screens and shared pieces
  index.css                   the design system: tokens (the Default theme), type scale, shared classes, motion
  theme/                      the theme engine: themes and styles as data, colour maths, CSS variables
.cursor/db/*.sql        the database schema (see "Schema" below)
scripts/                install, start, deploy (PowerShell for Windows, .sh for macOS)
desktop/                native-window launchers for dev and prod
docs/                   the documentation above
```

## Commands

Run from the repo root on Windows (PowerShell). The virtualenv is `.venv`.

| Task | Command |
|---|---|
| Start dev (API :8000, UI :5173) | `.\scripts\start-modern.ps1` |
| Backend tests | `.\.venv\Scripts\python.exe -m pytest backend/tests` |
| Backend lint | `.\.venv\Scripts\python.exe -m ruff check backend` |
| Frontend lint | `cd frontend; npm run lint` |
| Frontend type-check | `cd frontend; npx tsc -b` |
| Frontend production build | `cd frontend; npm run build` (then `npm run check:bundle`) |
| Attendance arithmetic | `cd frontend; npm run check:attendance` |
| Column filters (browser side) | `cd frontend; npm run check:filters` |
| Create or update the database | `.\scripts\init_db_windows.ps1` |

## Rules

These are the things that have caused, or would cause, real damage. Follow them without being asked.

**Work**
- Never commit to `main`. Branch, push, open a pull request. Code reaches prod only through GitHub and
  `scripts/deploy.ps1`; never edit files or run SQL in `C:\orion-prod`.
- Never commit `.env`, passwords, uploads or anything under `data/`.
- Do not add sample or seed data. A database starts empty; the only row the app creates is the first admin.
- Python packages are pinned: add one to `backend/requirements.txt` with `==` and refresh `backend/constraints.txt`
  (DEVELOPMENT.md, "Dependencies"). Every install passes `-c backend/constraints.txt`.
- CI (`.github/workflows/ci.yml`) has no database. A test must not reach for one: stub it, or skip unless its flag is set.
- A development default (session secret, database or admin password) must also be refused by `app/startup_checks.py`
  when `ORION_ENV=production`.

**Schema**
- The schema is the SQL in `.cursor/db/`. It is applied by the init scripts and again at every API start, so
  every statement must be safe to re-run and safe on a database that already has data
  (`IF NOT EXISTS`, additive). Never drop or rename a column in the release that stops using it.
- A new `.sql` file must be added to **both** `scripts/init_db_windows.ps1` and `scripts/init_db_mac.sh`, and to
  `entities.SQL_MIGRATIONS` (the list `app/migrate.py` applies and records in `orion_ods.schema_migrations`), or it will never reach
  prod. A failed migration stops the deploy and, in production, the start: never swallow one.
- `scripts/deploy.ps1` keeps its order: safety dump and `app.migrate` **before** the old server is stopped, rollback to the
  previous version when the smoke test fails. `/api/health/version` takes the commit from git at start, never from `data/release.json`.
  Change `test_deploy_tools.py` with it, and rehearse a change to it in a throwaway clone.
- Dev and prod on the office PC share one PostgreSQL role, `orion_user`. The SQL names it directly.

**Data ownership**
- **The SQL editor** (`sql_lab.py`, `sql_guard.py`) is for administrators only, audited in `sql_query_log` on every run, read-only unless `ORION_SQL_EDITOR=full` (production defaults to read-only) and the user turns on "Allow changes".
  It never reads the private tables (`PRIVATE_TABLES`), never changes the tables Orion's code owns (`OWNED_TABLES`: they change only through the application) and changes structure only in the `reports` schema. A new secret table goes
  in `PRIVATE_TABLES`; a new table with its own writer module goes in `OWNED_TABLES`. Never add a Copilot tool that runs SQL (see "AI Copilot").
- **Google Drive** is reached only through `gdrive_client.py` (a stand-in Drive for development, Google's REST API with credentials) and written about only by `gdrive.py`
  (the only writer of `gdrive_connection` and `drive_link`). Nothing confidential, no employee paper and no filed paper leaves Orion without the checks in `gdrive.copy_to_drive`; a bill
  is saved to Drive by choice and never held up by it (`sync_bill_quietly`); a token, code or Google answer is never logged or sent to the browser; production never runs the stand-in Drive.
- Bills are written only by `backend/app/billing.py`. There is no generic "Bill" entity.
- A revenue entry (`orion_ods.case_transaction`) that has a `bill_code` belongs to its bill. Only
  `billing.py` may write it. The generic Transaction form, the Excel upload and any new code must leave it
  alone. A bill has at most one `Prospective` entry and its entries always add up to its grand total.
- A letter's text is HTML that other users' browsers draw. It is stored only after `letterhead.clean_html`
  has rebuilt it from the short list of tags the editor makes. Never store or render it any other way.
- GST on a bill is paid in instalments (CGST and SGST, any number of payments). It is recorded or reversed only through
  `billing.record_gst_payment` / `reverse_gst_payment`, which need the confirmation, the day, the amounts (no more than is left) and the amount the
  person saw (`seen_paid`), or a reason to reverse, and keep every payment in `bill_gst_payment` for ever. Never a bare update of `gst_paid`, never delete
  a payment row, and never remove the confirmation screen.
- EPFO and ESIC charged on a bill are paid over in instalments, tracked bill by bill like GST: recorded or reversed only through `billing.record_statutory_payment` / `reverse_statutory_payment`
  (confirmation, the day, amounts no more than is left, the amount the person saw as paid, or a reason to reverse), every payment kept in `bill_statutory_payment` for ever, never a bare update of
  `epf_paid_amount` / `esic_paid_amount`, never a deleted row. Charged to the client they are inside the bill's taxable value and so inside Revenue; PAID to the authority they are a cost, on the day paid, against the bill's case, and reduce the margin,
  independent of payroll and attendance (salary is its own cost): that happens only in the view `orion_dw.expense_cost` (the expenses plus the payments not reversed), which every expense and
  margin reader must use, never `fact_expense_transaction` directly (`test_profit_and_loss.py`, `test_statutory_paid.py`). They are not entered as an Expense as well. A payment recorded on a bill must not also be typed as a bank entry.
- An issued bill's number never changes and is never reused. An edit creates a version; it does not replace
  history. The printed bill (`BillDocument.tsx`) keeps its own fixed colours, and the typeface and size are the bill's or the company's (`bill_fonts.py`, `billFonts.ts`),
  never the app theme's. Sizes in it are `em`, and in `billing_pdf.py` they scale with the size chosen; both draw every size the same way.
- Creating a bill, editing one and recording a payment take an `Idempotency-Key`, claimed inside the transaction that does the work
  (`idempotency.py`). A new endpoint that creates a bill, records money or sends something to a client must do the same, and its page
  must keep one key per form and ignore a second click with a ref.
- The bank balance is never stored: it is the opening balance plus the view `orion_ods.bank_movement`, which reads client payments,
  expenses and GST paid from where they already live. The Bank (`bank.py`, the only writer of the `bank_*` tables) never writes those
  tables and never records them a second time: a payment is recorded on its bill, an expense in Expenses. A `bank_entry` is for money with
  no record elsewhere, is voided with a reason and never deleted, and the Bank's money-recording endpoints take an `Idempotency-Key`. A
  statement line is matched automatically only when it is certain both ways (`bank_match.auto_pairs`); anything else waits for a person.
  Every money event names its account (`account_id`; none means the first account), a statement line matches only its own account's movements, and a cash
  account has no statement. Bank screens and the Cash dashboard tab are for `bank_access` only, in the router and in every Copilot tool that could read them.
- An expense reaches the bank when it is PAID, not when it is entered: `payables.py` is the only writer of `orion_ods.expense_payment`, which the view
  `bank_movement` reads (never an expense's `transaction_date`). A payment is recorded or reversed only with the confirmation, the amount the person saw as
  already paid (`seen_paid`) or a reason to reverse, and an `Idempotency-Key`; it is kept for ever, never deleted. A paid expense stays Committed and is never
  worth less than was paid (the trigger `expense_keeps_its_payments`); never add code that cancels, lowers or deletes one around it.
- Salary reaches the bank in pay runs: `payroll.py` is the only writer of `orion_ods.salary_run` and the only thing that marks a salary line paid or takes it back, and
  the view `bank_movement` reads the runs (one movement per run). A run is recorded or reversed only with the confirmation, the lines and total the person
  saw or a reason to reverse, and an `Idempotency-Key`; it is kept for ever. A line in a run stays as it was paid (the trigger `salary_line_follows_its_run`);
  never add code that flips `salary_paid`, edits or deletes a paid line around it.
- Money on a bill is calculated in two places that must agree: `backend/app/billing.py` (authoritative) and
  `frontend/src/billing/billCalc.ts` (live preview). `backend/tests/bill_vectors.json` holds the figures both must produce
  (`test_bill_vectors.py`, `npm run check:bill`): change a calculation or a limit, and the vectors, on purpose.
- **Filed documents** (`orion_ods.document` with a `source_type`) are written only by `documents_filing.py`, and no other code changes, moves,
  deletes or re-versions one (`documents.refuse_filed`). A bill, an employee's papers or an EMD's papers are changed where they are made; the filing follows.
  A person moves one by choosing where it is kept (`documents_filing.set_choice`), not by changing the document. A new place a document is found in is a `document_placement`, never a second document. Filing after a save is `reconcile_quietly`: it must never fail the save.
- What a client **held back** from a payment (TDS, penalty, rounding, other) is `orion_ods.bill_payment_deduction`, written only by `billing.record_payment` /
  `reverse_payment` (and the Form 26AS tick by `tds.py`). A bill is settled by cash + deductions: the revenue entry holds the whole, the view `bank_movement` shows
  only the cash, and a deduction is kept for ever and reversed with its payment, never deleted or edited. No other code may lower a bill's open amount "because of TDS". Only TDS is not a cost: a penalty, a short payment (Other) and rounding are a cost on the day of the payment (the view `orion_dw.expense_cost`, as for EPFO/ESIC paid), never typed as an Expense as well.
- A **credit note** (`credit_notes.py`, the only writer of `orion_ods.credit_note`) takes money off what a bill still owes without changing the bill: it is made, then approved by
  someone other than its maker or by an admin (a write-off by an admin only), with the confirmation and the amount seen; it takes effect only through `billing.apply_credit` in one
  transaction (the bill's `credited_*` figures, its open revenue entry, its GST due) and gets its number `CN FY/seq` then; it is kept for ever and reversed only by an admin with a reason.
  Every reader of what a bill owes or its GST due subtracts the credited figures; `test_credit_notes.py` fails when a dashboard reader does not.
- **Tasks** (`tasks.py` and the `task_*.py` modules) own the `task*` tables, one writer each (see the docstring of `task_common.py`); the SQL editor never changes them (`OWNED_TABLES`). Who may see a project is decided only by
  `task_common.role_in` / `visible_sql`: a private project must not appear in a list, a search, a report, the calendar, a notification or a file download for someone outside it, and an unknown and a forbidden project answer the same
  (not found). A task is never erased (`task_kept` trigger) and its history (`task_activity`) is append-only; it is finished only through a move to a done status (`tasks.transition` / `decide_review`: blockers, open sub-tasks, a review where the
  project requires one). A change carries `expected_updated` and a stale one is refused (409); creating a task, a comment or a to-do takes an `Idempotency-Key`. A comment is rendered by the safe Markdown renderer, never as HTML; a
  file is checked by `documents.check_file` and served with `nosniff`, only to someone who can see its task. A person's to-do lists are readable only by that person. A repeating task makes only the latest missed run
  (`task_templates.run_due`). Record links to bills, cases and so on require the access flag of that kind of record. Never add a Copilot tool or a SQL path that reads another person's to-do list.
- **Attendance** (`attendance.py`) is the only writer of the `attendance_*` tables and of the salary lines and expenses a posted register enters (they carry `attendance_line_id` and
  are locked in the generic forms). A register is posted only with the confirmation, the count and total the person saw and an `Idempotency-Key`; it is never changed while posted, and
  reopening it is refused once any of what it entered has been paid. The line arithmetic is in two places that must agree (`attendance.calculated_amount`, `attendanceCalc.ts`):
  `backend/tests/attendance_vectors.json`, `test_attendance.py`, `npm run check:attendance`.
- **A won opportunity's follow-ups** are created, settled and withdrawn only by `opportunity_followups.sync`, from the records (a case or EMD that
  exists settles one); only a person's "not required" dismisses one, and it is kept in `opportunity_followup_event`. Updating them after a save is
  `sync_quietly`: it must never fail the save.
- **PDF tools** (`pdf_tools.py`) keep nothing: a file, a result or a password is never written to disk or the database, and a log line holds the tool, the user id and byte counts, never a file name,
  a password or anything from a file. Limits live in `pdf_tools.py`; the upload is refused by `request_limits.RequestSizeLimitMiddleware` before it is all on disk. Orion never guesses or breaks a password.
- GeM is read only through `gem_client.py` and MP Tenders only through `mptenders_client.py`: their public pages that ask for no
  captcha, at least `ORION_TENDERS_REQUEST_GAP_SECONDS` apart. Never sign in to either, never answer or work around a captcha (MP
  Tenders' own search has one: do not use it), and stop on a refusal (403/429) rather than retrying.

**Access**
- A session is a row in `orion_ods.app_session` and can be ended; read the cookie only through `sessions.user_for_token`. A change to
  a password, an account's active state or anything else that should sign someone out calls `sessions.revoke_all(..., cur=cur)`
  in its own transaction.
- Production pages obey a Content-Security-Policy (`security_headers.py`): no inline scripts (put one in `frontend/public/`), and a
  new host for a script, font or API call must be added to `build_csp` or the browser blocks it. Set and clear the session
  cookie with the same attributes (`cookie_secure`). Test a front-end change that loads something new against the production
  build (`ORION_SERVE_FRONTEND=1`), not only the dev server, which has no policy.
- A route that can be reached without signing in (sign-in, reset, registration) is limited with `_limited(...)` and
  `throttle.record(...)`, with a rule in `throttle.RULES`.
- Every API route has a permission dependency from `backend/app/dependencies.py`. A new route needs one.
  The frontend hides what a user cannot do, but the server is what enforces it.

**Database**
- Reach the database only through `db_cursor()` / `get_connection()` (a pool: `close()` gives the connection back). They reset a returned
  connection by rolling back, so never set session state on one (`SET`, advisory locks, temp tables, `LISTEN`, autocommit); use
  `raw_connection()` for that. Never hold a connection while waiting on something slow. A new `psycopg2.connect` must be added to the
  allow-list in `test_db_pool.py` on purpose.

**Logging**
- Use `logging.getLogger(__name__)`; never `print` (a test fails on it). Never put a query string, token, password, cookie or request
  body in a message. An `except Exception` re-raises or logs. A condition that is normal on a machine is DEBUG, not WARNING: the
  Admin > System page flags any error in the last hour. The result of a background job is written to its own table; `health.py` reads it.
- `/api/health` must keep returning `{"status":"ok"}` (the desktop launchers poll it).

**AI Copilot**
- The model reaches data only through a tool in `backend/app/ai/tools/`. A tool has a permission (`needs`), a schema,
  and, if it changes anything, a confirmation the person gives on screen. Never add a tool that runs SQL, takes a free
  query, or acts on many records at once. Numbers the model states must come from a tool; tool output is untrusted data.
- Only `ai/config.py` names a model, a limit or a key. Keys never leave the server.
- Local first: Orion's own rules, then the model on this computer, and a cloud model only when `routing/policy.py` allows it (environment, the
  organisation's policy, the person's choice, not sensitive, within budget). Never send application data, names or the conversation to a cloud
  model outside that path, and never log a question or an answer in the route log.

**Frontend**
- Call the API only through `frontend/src/api/client.ts`, with types in `types.ts`.
- A table that lists data uses `ui/DataTable`, `dashboard/ReportTable` or `dashboard/RecordTable`, which give every column a filter (`tables/`). Where the rows are paged on the server, a column filter
  is a `?f=` parameter built only by `column_filters.build`: never put a request's column name or value into SQL text. `npm run check:filters` must pass.
- Use the design tokens in `index.css` (`brand`, `alt`, `text-accent`, `bg-primary`, `bg-surface`, `.panel`,
  `.t-h1` ... the type scale), not raw Tailwind hues like `blue-600`, `text-white` on themed surfaces, hex values or
  `dark:` colour pairs: a person can pick another theme (`frontend/src/theme`), and anything with a colour of its own
  will clash with it. `brand` is the accent (teal in Default) and Orion; `alt` (ink blue) is Tally. The printed bill and
  the letterhead are paper and keep fixed colours.
- A new theme is one object in `theme/themes.ts`; `npm run check:themes` must pass.
- The application has two interfaces (`experience`: Classic, Lumen) over the same pages. Areas of the navigation are listed once, in `components/nav/navigation.ts`. Everything specific to Lumen's look is in `frontend/src/lumen.css`
  under `html[data-experience='lumen']` and `components/lumen/`; a page never decides its own colours or shape for one of them. A new bell, button or top-bar item is added to both top bars. A shared component that draws differently in Lumen (`useLumen()`) must show the same data and offer the same actions in both forms; `npm run check:lumen` must pass.
- A bill number is drawn with `components/billing/BillNumber.tsx` (a card on hover, the bill in a new tab), never as plain text; a link that
  takes someone off the screen they are on is a `TabLink` / `openInNewTab`, not `navigate()` (the native window needs `desktop/orion_windows.py` for this).
  `npm run check:links` must pass.
- An amount of money is typed in `components/ui/MoneyInput.tsx` (Indian commas as it is typed, the amount in words under it), never a bare number input. The page keeps the
  plain number (no commas), so nothing it checks or sends changes. A number field of the entity registry that is money says `"money": True`. `npm run check:money` must pass.
- Choosing several values (cities, types, tags, columns) uses `components/ui/MultiSelect.tsx` (search, tick, select all, chips; a typed value is allowed with `allowCustom`),
  never a comma-separated text box or a native `<select multiple>`. The `max` it shows must be the limit the server enforces.
- Pages are loaded on demand: add a page to `workspaceRoutes.tsx` with `lazyPage(...)`, never a plain `import`, and keep heavy libraries
  (`recharts`) out of the shell, `Layout`, contexts and the Copilot panel. `npm run build && npm run check:bundle` must pass.

## Before you say a change is done

1. `pytest backend/tests` passes. The contract tests in `test_contracts.py` fail when a form field, a
   warehouse column, a dashboard tab or a SQL file no longer matches the other side.
2. `ruff check backend` and `npm run lint` pass (they find bugs: conditional hooks, missing effect dependencies, unused names, a
   swallowed error with no stated reason). Do not reformat files you did not change, and do not silence a rule with a comment
   unless you say why on the same line. `npx tsc -b` and `npm run build` pass. The dev server does not type-check; the prod build does. If you touched
   colours, the stylesheet's tokens or `frontend/src/theme`, `npm run check:themes` passes too (`pytest` runs it).
3. You have checked [docs/change-impact.md](docs/change-impact.md) for what else your change touches.
4. If you changed the schema, the API was restarted twice against a dev database with no `Could not apply`
   message in its log.
5. If you changed how a feature behaves, its section in `docs/features.md` is updated in the same change.
