# Features

One section per feature: what it does, where its code is, which tables it owns, and the rules it must keep.
Update a section in the same change that alters its behaviour. For cross-feature effects see
[change-impact.md](change-impact.md).

Paths are relative to the repo root. `ui` means under `frontend/src/`, `api` means under `backend/app/`.

---

## Sign-in, users and access

**Does.** Sign in and out, self-service account requests that an admin approves, password reset by email,
user administration (role, access flags, activate, reset password, delete), own profile and photo.

**Where.**
- ui: `pages/LoginPage.tsx`, `pages/ResetPasswordPage.tsx`, `components/AuthFrame.tsx`, `pages/AdminPage.tsx`,
  `pages/SettingsPage.tsx`, `context/AuthContext.tsx`, `components/ProtectedRoute.tsx`
- api: `routers/auth_router.py`, `routers/users_router.py`, `auth.py`, `sessions.py`, `throttle.py`, `signup.py`,
  `avatars.py`, `mail.py`, `dependencies.py`
- ui for sessions: `components/SignedInDevices.tsx` (Settings > Profile), the "Sign out everywhere" button in Admin
- **Sign-in pages.** In Lumen the sign-in, account request, forgot-password and reset pages are one glass card: a gradient panel with the company's line and what Orion holds beside the form (on a phone, a short header strip over the form); Classic keeps its side panel. The first box is focused; a password box warns while Caps Lock is on; a new password (request and reset) shows a four-step meter in words (advice only, the server refuses under 8 characters) and whether the two copies match (`components/ui/PasswordStrength.tsx`); a reset link that is used up or expired, and a successful reset (which signs the person out everywhere, `sessions.revoke_all`), say so plainly.
- **Welcome tour** (`components/welcome/WelcomeTour.tsx`, a separate download mounted in `Layout` for signed-in people): three steps - choose Classic or Lumen (applied behind the dialog as it is chosen), what your own access opens (each tile goes there; nothing you cannot open is shown), and four quick ways around (Ctrl+K, +, Copilot, photo in Settings). It opens by itself once for an account less than 30 days old (`created_timestamp` is in the signed-in user) and is remembered in this browser (`orion-welcome:<id>` in localStorage), so another browser shows it once more; Settings > Profile has "Show the welcome again" (the window event `orion-open-welcome`).
- **In Lumen** Admin opens on the people, not a table: four counts (people, active, administrators, waiting to be let in, which opens Requests), a search, one-tap filters and a card for each person with
  their role, whether they are active and what they can reach, and "Manage" (opens that person in Manage user) and "Account page" (`components/admin/LumenPeople.tsx`); account requests are cards you open instead of a
  drop-down. Everything below the cards (approve with a role and access, reject, manage, create, system) is the same. Settings > Profile is a hero with the photo (camera button on it) and one "Your details" form
  (name, email, phone, one Save that sends only what changed) beside where you are signed in.
- tables: `orion_ods.app_user`, `orion_ods.signup_request`, `orion_ods.app_session`, `orion_ods.auth_attempt`
  (`.cursor/db/migrate_auth_security.sql`); files in `data/avatars/`, `data/mail/`

**Rules.**
- The first admin is created from `ORION_ADMIN_USERNAME` / `ORION_ADMIN_PASSWORD` only when `app_user` is empty.
  Changing those values later does nothing.
- A role sets default access flags; flags are then stored per user and win over the role. A write flag forces
  its read flag on (`auth.WRITE_IMPLIES_ACCESS`).
- Each segment has its own pair of flags, set in Admin: Operational data (`ods_*`), Warehouse (`dw_access`), Tally
  working copy (`tally_access`), Tally warehouse (`tally_dw_access`), **Billing** (`billing_access` view,
  `billing_write` raise, edit, cancel, record payments and send), **ETL** (`etl_access` view pipelines and history,
  `etl_write` run them), **Letterhead** (`letterhead_access` read and print letters, stamp PDFs and use the PDF tools,
  `letterhead_write` write, edit and delete letters), **Documents** (`documents_access` open and download documents,
  `documents_write` upload, edit and delete them and see Confidential ones), **Bank** (`bank_access` see the balance, the
  ledger and the Cash dashboard tab, `bank_write` set the opening balance, enter, void, upload and match; admins only until
  given), **AI Copilot** (`ai_access`, on by default for everyone: use the assistant, which still only does what the person's other flags allow) and the two dashboards. `dw_write`, `tally_write` and `tally_dw_write` no longer control
  anything, since loading moved to ETL; the columns stay for one release and Admin no longer shows them.
- The first time `billing_*` and `etl_*` were added, they were filled from what each person could already do (Billing
  from ODS access, ETL from the old load flags), so nobody lost access. `letterhead_*` and `documents_*` were new, so
  they were given to admins and editors, which is what a new user of those roles gets. `bank_*` were new and are given to
  admins only (the balance of the firm's account is the most sensitive figure in the application); an admin gives them
  to others in Admin.
- An account request does not create a user until an admin approves it.
- **A session is a row the server can end** (`sessions.py`, `app_session`). The cookie is `<random id>:<expiry>:<signature>`; a
  request is accepted only if the signature is ours (`ORION_SESSION_SECRET`), the row is neither revoked nor expired, and the
  person is still active (`sessions.user_for_token`, used by `dependencies.get_current_user` and the chat socket). So a copied
  cookie stops working when the person signs out. Sessions are ended on: sign-out (that browser only), a password change or reset
  (all of that person's sessions, in the same transaction), disabling the account, an admin's "Sign out everywhere"
  (`POST /api/users/{id}/sign-out`), and the person's own "Sign out" / "Sign out of all other devices" in Settings
  (`GET/DELETE /api/auth/sessions`, `POST /api/auth/sessions/revoke-others`). Lifetime is `ORION_SESSION_TTL_DAYS` (7), fixed from
  sign-in. An open chat connection re-checks its session every 30 seconds and closes when it has ended. When any request gets a
  401 the app returns to the sign-in page. Ended sessions are deleted a week later. A new way to change credentials must call
  `sessions.revoke_all(..., cur=cur)` inside its transaction. The first deploy of this made every old cookie invalid, so everyone
  signed in once.
- **The browser is told how to protect the page** (`security_headers.py`, a plain ASGI middleware on every response). A
  Content-Security-Policy: scripts only from this server (no inline, no eval), nothing sent to another host (`connect-src 'self'`,
  which includes the chat WebSocket), fonts only from Google Fonts, previews of files the browser holds (`blob:`), inline styles
  allowed because React sets them. Also `X-Frame-Options: SAMEORIGIN`, `nosniff`, `Referrer-Policy: same-origin` (a reset
  link carries its token in the address), a `Permissions-Policy` that switches off camera, microphone, location and payment,
  `Strict-Transport-Security` (31 days) only on HTTPS, and `Cache-Control: no-store` on JSON answers. There is deliberately no
  `frame-ancestors`: a PDF preview is a blob page that inherits the policy, and the browser's PDF viewer sits in a
  `chrome-extension://` frame that `frame-ancestors 'self'` refuses, which blanked every preview; `X-Frame-Options` does the job.
  `ORION_CSP` = `enforce` (default), `report-only` (the browser logs what it would block, blocks nothing: use it to find what a
  change broke) or `off`. A new script, font or API on another host must be added to `build_csp` or production blocks it;
  `test_security_headers.py` scans the frontend for hosts and for inline scripts. The interactive API pages (`/docs`) are not
  served in production (`ORION_API_DOCS=1` turns them on).
- **Profile photos need a signed-in person.** `GET /api/media/avatars/{id}.jpg` (the address stored in links, kept as it was) is a route with
  `get_current_user`, not a public static folder; only `<number>.<jpg|jpeg|png|webp>` is accepted. A page's `<img>` sends the cookie
  by itself. The same photo is also at `/api/auth/avatar/{id}`.
- **Other websites may not call the API with a person's cookie** (`security_headers.cors_options`). Production trusts no other origin:
  the UI is served by the same process, so it needs none, and a private address range is not an origin to trust. If a second address
  genuinely serves the UI, list it exactly in `ORION_CORS_ORIGINS` (comma separated, `*` is ignored). Development also accepts this PC
  and the private/Tailscale ranges so a phone can reach the Vite server. Methods and headers are named (`CORS_METHODS`, `CORS_HEADERS`):
  a header the UI starts to send must be added there, and `test_avatars_and_cors.py` checks the ones it knows.
- **The session cookie is Secure when the browser used HTTPS** (`security_headers.cookie_secure`): it is then never sent over
  plain HTTP, so it cannot be read off the network. `ORION_COOKIE_SECURE` = `auto` (default: exactly when the request was HTTPS,
  as uvicorn reports it behind the Tailscale proxy), `1` (always) or `0` (never). `1` stops anyone signing in over a plain
  `http://` address other than this PC's own (`http://127.0.0.1` and `localhost` are still accepted by Chromium and Edge, which the
  desktop window uses); use it once everyone uses the HTTPS address. Logout clears the cookie with the same attributes.
- **Guessing is slowed down** (`throttle.py`, `auth_attempt`). Every sign-in, reset-email request, account request and reset-link
  attempt is a row (name lower-cased, address; never a password or token). Sign-in is refused with 429 and `Retry-After` before the
  password is checked when, in the last 15 minutes, the same name from the same address has failed 5 times (a correct sign-in clears
  that count), one name from anywhere 15 times, or one address 30 times (skipped for `127.0.0.1`/`::1`, which is what a local proxy
  looks like). Refused attempts are not counted again, so a block ends 15 minutes after the attempts that caused it. Reset emails:
  3 per name and 8 per address per hour (and 40 in all); account requests: 5 per address and 30 in all per hour; wrong reset links:
  10 per address per 15 minutes. A wrong name, a disabled account and a wrong password all cost one bcrypt check, so timing says
  nothing. The address is `request.client.host`; behind a proxy uvicorn replaces it with the forwarded address. The policy is the
  `RULES` table in `throttle.py` and is tested (`test_sessions_and_throttle.py`; the half that needs the dev database runs with
  `ORION_AUTH_DB_TESTS=1`).
- With `ORION_SMTP_HOST` empty, mail is written to `data/mail/` instead of being sent.

**Used by.** Every other feature, through the dependencies in `dependencies.py` and `user.can_*` in the UI.

---

## Operational Data (generic records)

**Does.** Browse, search, create, edit, delete and Excel-upload the business records: Business Domain,
Capability, Expense Type, Client, Contact, Case, Opportunity, Employee, Employee Transaction, Car, Car Transaction,
Transaction (revenue), Expense Transaction, EMD. "Review" mode is read-only; "Change" mode opens after a
confirmation dialog.

**Where.**
- ui: `pages/OrionDataPage.tsx` (the four ways in; in Lumen `components/data/DataDesk.tsx`), `pages/OperationalDataPage.tsx`, `components/EntityForm.tsx`,
  `formPayload.ts`, `components/PreviewRecords.tsx`, `components/ExcelUploadPanel.tsx`,
  `components/data/*` (workbench chrome, catalog, write gate)
- api: `routers/entities_router.py`, `entities.py` (the `ENTITIES` registry), `payload.py`, `db_utils.py`,
  `excel_import.py`, `xlsx_io.py`, `query.py`, `location.py`
- tables: the fourteen `orion_ods` business tables, `orion_ods.employee_document` and `orion_ods.emd_document`

**In Lumen** the way in is a task list rather than a choice of "review or change" (Classic is unchanged; the same pages, permissions and warning). `/data/orion` asks **What do you want to do?** and offers one tile for each thing
people do (Add an employee, a client, a case, a contact, a tender or lead, a vehicle; Record an expense, income, salary or an EMD), a search over the tasks, two tiles for what is already saved ("Change a record" and "Upload from Excel", each asking which records, then the change warning, then opening that type's Edit form or its Excel upload),
and "Look something up" (the record types by group, each opening its records). A tile still shows the change warning, then opens the Add form for that record type: `/data/operational?intent=change&entity=Employee&mode=create` (`mode=edit` opens Edit and `mode=upload` the Excel upload; `?entity=Employee` alone
opens that type's records). "Clients", "Cases" and "Employees" tiles open the directories of their pages (see Clients, and Cases, employees and accounts). The warehouse is under "For reporting".

**How it works.** `ENTITIES` describes each entity: table, primary key, and `form_fields` with a type per field.
The API serves that description. The frontend builds the form and the change preview from it, and the backend
builds the Excel template and reads uploads with it. Adding a field is mostly adding one entry to
`form_fields`, plus the column; [change-impact.md](change-impact.md) lists everything else a column touches.

**Rules.**
- Every write through the app records the signed-in user: `created_by` on insert, `last_updated_by` on every edit,
  Excel upload included, and `record_deleted` (table, code, who, when) on delete. These are plain user ids with no
  foreign key. The ODS keeps only current values; history is read from the warehouse.
- Codes such as `CL-0007` are generated by the database (`orion_ods.next_code`); the app never sets them.
- Derived fields are computed by the app, the same way on a form and in an upload: `amount_after_tax_gst` =
  amount + tax + GST (a blank tax or GST counts as 0, so an amount alone still gets a total), `driven_km` = final -
  initial reading, `month_year` from the transaction date. An update that sends only some of the fields works the
  total out from the stored values of the others, so changing only the amount cannot leave the old total behind. A
  total that is sent has to equal the sum, give or take a rupee of rounding, or the save is refused; a total sent back
  unchanged on a stored record is left alone.
- What a field may hold is checked in `payload.clean_payload`, the one place every form and Excel row goes through:
  numbers must be finite (NaN and Infinity are refused, because NaN makes every sum NaN and is never equal to itself,
  so the warehouse would give the row a new version on every load), integers must fit the column, a dropdown must be
  one of its options (stored in the option's own spelling whatever case was typed), and a NUL character is refused. A
  value the database still rules out comes back as a 400 with a message, never a 500. A NaN stored before this check
  existed is shown empty so its record can be opened and corrected, and the warehouse loader treats it as unchanged.
- An Excel upload inserts, or updates the record a row is about. A row names its record by a column holding the
  record's code (a download has one), or is matched on the entity's merge key (`MERGE_KEYS`, compared as numbers and
  dates where the column is one, as text otherwise). A key that matches more than one record is refused with the codes,
  never guessed, an unknown code is an error, and one error stops the whole file with nothing saved (the errors
  carry their row in the sheet). A blank merge key falls back to `MERGE_FALLBACK` where there is one (an opportunity
  without a tender id is matched on its name). Blank cells do not wipe stored values, so a value can be changed by a
  file but not cleared. The keys of Expense Transaction and Car Transaction include the amount and the opening
  reading, so a file never replaces a different expense or trip of the same day; to correct one, give its code.
- A lookup field (a `select` with a `source_table`) shows names in the form and stores the other record's code:
  a case's client, an employee's manager, a capability's head (`capability_head_code`, an employee) and a client's
  group (`client_group_code`, another client, shown as "name — code"; a client cannot be its own group). Deleting a
  record that others still point at is refused with a message, and so is saving a pointer to one that is gone.
- **Two people editing one record.** The edit form sends only the fields that were changed, together with the record's
  `last_updated_timestamp` as it was opened (`expected_updated`). `entity_service.change` refuses with 409 when the record
  has been saved by anyone since ("changed by X after you opened it"), and the update itself is one statement with the
  version in its `WHERE`, so two saves at the same moment cannot both win. The form then offers "Open it again with the
  latest values". A caller that sends no version (the Copilot) is held to the version it read at the start of the call.
- **Received money has a bill** (Transaction): a revenue line that is Committed (received) must belong to a bill, so the
  form, the Excel upload and the Copilot refuse a new one without a `bill_code`, or a Prospective one made Committed
  (`entities.invalid_reason`, and the trigger `case_transaction_committed_needs_bill` in `migrate_data_rules.sql` that holds
  the same rule for every way of writing). A Committed line with no bill stored before the rule can still be corrected where
  it stands. The Status field on the form says that a Committed line already there counts in the bank balance. Money with no
  bill is a Bank entry (`other_receipt`).
- **Amounts of money are typed with commas and read back in words.** Wherever a person types rupees (the record forms, a bill's rate and charges, a payment, a bank entry, the
  opening balance, a tender's value range) the field shows the Indian commas as it is typed (1,23,456.50), keeps the cursor after the same digit, treats Backspace and Delete
  across a comma sensibly, and shows the amount in words under it ("One Lakh Twenty Three Thousand ... Only"), updated with every key. A field in lakh says what the rupees really
  are. What the page holds, checks and sends is still the plain number (`components/ui/MoneyInput.tsx`, `billing/moneyText.ts`, `npm run check:money`). A number field of the
  registry that is money carries `"money": True`.
- **Rules about values** (`payload`, `entities.invalid_reason`, and the database itself in `migrate_data_rules.sql`, so an
  Excel upload meets them too): kilometres, odometer readings and a price per kilometre are never negative, and a car's
  final reading is never below its initial one (so Driven KM is never negative); an employee is never their own manager and
  manager chains never go round in a circle; a client's group chain never goes round in a circle (and a client is never its
  own group). The constraints are `NOT VALID`, so rows stored before them are not checked and cannot stop the migration;
  every new or changed row is. The loop checks are triggers on `employee.manager_code` and `client.client_group_code`, so
  a loop that is already stored does not block an unrelated edit of one of its rows.
- A field marked `readonly` is never accepted from the client.
- A record can be locked by another feature: `entities.locked_reason` returns why, the API then refuses
  update and delete with 409, and the form opens read-only. Today this locks a Transaction that belongs to a
  bill (see Billing).
- There is no "Bill" entity here on purpose.
- **An employee's personal details are private.** Aadhaar Number, PAN No and Monthly Salary (Decided) are columns
  of `orion_ods.employee` and fields of the Employee form. Each is checked and tidied wherever an employee is
  saved, the form and the Excel upload alike (`field_rules` in the entity, `employee_ids.py`): an Aadhaar number is
  12 digits with a correct check digit and is stored without spaces, a PAN is five letters, four digits and a
  letter in capitals, a salary is between 0 and 1,00,00,000. They are listed in the entity's `private_columns`, so
  the table preview and the Excel export do not read them at all for someone who can only view operational data
  (they are not shown, searched or sorted); people who can change operational data see them. Aadhaar and PAN are
  never loaded into the warehouse. The monthly salary is (`dim_employee.monthly_salary`), so a change of salary is
  kept as a version, but it is listed on the warehouse Employee page and its export, and in a record's history, only
  for people who can change operational data (`private_columns` and `preview_public` in the Employee spec in
  `dw_sync.py`, `dw_preview`). No dashboard uses it yet.
- **An employee's documents** (`employee_documents.py`, `routers/employee_documents_router.py`, panel
  `components/data/EmployeeDocuments.tsx`, table `orion_ods.employee_document`): Aadhaar and PAN scans and other
  files. On the Add screen the files are chosen and queued, and uploaded as soon as the employee is saved (the
  create route returns the new code for that); on the Edit screen they are uploaded and listed live. If one upload
  fails after the employee is saved, the message names it so it can be added from Edit. Each has a kind (Aadhaar card, PAN card, Photo,
  Bank passbook or cancelled cheque, Address proof, Police verification, Educational certificate, Appointment
  letter, PF or ESIC form, Other; Other needs a title), an optional note, and who uploaded it and when. PDF, JPG, PNG,
  WEBP, DOC(X) and XLS(X), up to 8 MB each and 30 per employee. The type comes from the extension and the file's
  first bytes must agree with it; only PDFs and images are shown in the browser, the rest are saved. The file is
  kept in the database, not on disk, so the encrypted daily backup includes it. Every route needs permission to
  change operational data, for viewing as well as uploading. Deleting an employee deletes their documents.
- **Contacts at clients** (entity Contact, table `orion_ods.contact`, code `CON-`): the people known at a client, one row each. It
  belongs to a client (required) and may name a case; it holds the person's designation and department, a role (decision maker,
  accounts or billing, procurement or tender, site in-charge, technical, escalation ...), a status (Active, Inactive, Left
  organisation), the day the relationship began and, if it did, ended, whether this is the client's primary contact, phone,
  alternate phone, e-mail, preferred way to reach them, place, who in the firm looks after the relationship (an employee), the day
  they were last contacted, the day the next follow-up is due and notes. The rules are in `entities.invalid_reason` and in named
  CHECK constraints of `migrate_contacts_emd.sql` (messages in `entity_service.CONSTRAINT_MESSAGES`): a contact cannot have ended before
  it began, and a primary contact must be Active. The same person at the same client is one contact (`MERGE_KEYS`).
  E-mail, phone, address and notes are **not** loaded into the warehouse.
- **EMDs** (entity EMD, table `orion_ods.emd`, code `EMD-`): the earnest money the firm deposits for a tender, kept against the **case**
  that the win became (required) and optionally the opportunity. It holds the amount (typed with commas and read back in words),
  the mode of payment (online, demand draft, bank guarantee, FDR, cheque, cash), the document number and date, the bank and branch,
  the day deposited, the day an instrument lapses (`valid_until`), a status (Deposited, Refund requested, Refunded, Adjusted against
  security deposit, Forfeited, Cancelled), when the refund is due, when it was asked for and received, how much came back, how much was
  kept back (a forfeit or an adjustment), the refund's reference, and remarks. Rules (form, Excel and the database alike): the amount is
  more than zero, what came back and what was kept together cannot be more than the EMD, a Refunded EMD says the day the refund came,
  and an instrument cannot lapse before it was issued or deposited. An EMD with a document number is told apart by case and number
  (`MERGE_KEYS`). **An EMD is not written into the Bank.** The deposit and its refund are money the Bank does not see unless someone
  records them as bank entries; the dashboards say what is still out, not what the bank holds (see `money-flow.md`).
- **An EMD's documents** (`emd_documents.py`, `routers/emd_documents_router.py` under `/emds`, the same panel as an employee's with
  `kind="emd"`, table `orion_ods.emd_document`): the payment receipt, a copy of the demand draft or bank guarantee, the FDR receipt, the
  tender notice, the refund request and the proof of refund, or Other. They work exactly as an employee's do (same file types, same
  checks of the first bytes, 8 MB each, at most 30 per EMD, kept in the database so the backup includes them, queued on the Add
  screen and uploaded when the EMD is saved). Viewing needs access to operational data, adding and deleting need permission to change
  it. Deleting an EMD deletes its documents.
- **In the warehouse and the dashboards.** Contact is the dimension `dim_contact` (versioned) and EMD the fact `fact_emd` (a version
  per change, dated by the deposit day, with the case, client, capability and domain as they were then). The **Pipeline** tab shows
  *EMD held by clients*, *EMD refund overdue* and *EMD forfeited or deducted* (positions as at today, which the period does not
  narrow; each opens by year and dimension and to its rows), a chart of the amount by status for the period, and the table *EMD still
  to come back* (earliest refund first, flagging a refund past due and an instrument that lapses in 30 days). The **Controls** tab shows
  *Clients with no active contact* and *Follow-ups due* (an Active contact whose next follow-up date has come) with their tables. The
  record sets `emds`, `emds_open`, `emds_overdue`, `emds_not_returned`, `contacts` and `contacts_follow_up` need access to operational data.

- **Notifications for a won opportunity** (`opportunity_followups.py`, `routers/followups_router.py`, `context/FollowupsContext.tsx`,
  `components/followups/FollowupsBell.tsx`, tables `orion_ods.opportunity_followup` and `opportunity_followup_event`): the moment an
  opportunity is saved as **Closed Won**, two things are asked of the people who can change operational data: **create its case** and
  **record its EMD**. They show on the bell at the top (a count, a list, and a short message when a new one arrives; they are looked
  at again every minute, when the window is used again, and after anything is saved on the Operational Data page).
  - *It keeps coming back.* A notification stays until the case (or the EMD) exists, or a person says it is **not required**. "No case
    needed" / "No EMD needed" asks for an optional reason (kept, with who and when) and is the only way one goes away without being done.
    A dismissal can be taken back from the Not required tab ("Remind me again"). Nothing else dismisses one.
  - *It settles itself.* It is done as soon as the opportunity has a case (a case that names the opportunity, or the one the opportunity
    became) or an EMD (one that names it, or one on its case), however it was made: the notification's form, the ordinary record form,
    an Excel upload or the assistant. It is worked out from the records. If that case is later deleted, it is asked for again.
    If the opportunity is changed back from won, the notifications are withdrawn and return if it is won again.
  - *Clicking it opens the form.* "Create case" / "Record EMD" opens the Operational Data form for a new Case or EMD with the **opportunity
    already chosen and fixed** (the field is disabled and says why); the case form starts with the opportunity's name as the case name, and the
    EMD form offers only the cases of that opportunity (the case is chosen for you when there is one) and fills the tender number. An EMD
    belongs to a case, so while the opportunity has none the EMD notification says to create the case first and the form offers a button
    for it. After saving, the notification clears and the form closes. The lock is on the screen; the server accepts the same
    data from any other way of saving.
  - *The case and the opportunity are linked.* A case made for an opportunity becomes the case the opportunity became
    (`opportunity.opportunity_case_code`, which the Pipeline dashboard's "what the wins now bill" reads) when the opportunity has none.
  - *Starting out.* The first time the table was created, every opportunity that was already won was recorded as settled, so nobody is told
    about last year's wins. Only wins after that ask for a case and an EMD.
  - The list is for people who can change operational data (`require_ods_write`), since only they can act on it.

**Depends on.** Sign-in (ODS access / write).
**Used by.** The Orion warehouse reads these tables (and the Orion dashboards read it, not these). Billing reads Case and Client and
writes Transaction.

---

## Billing

**Does.** Raise a tax invoice for a case, print it, edit it with version history, cancel it, mark its GST as
paid, and record the payments received against it.

**Where.**
- ui: `pages/utility/BillingPage.tsx` (register; in Lumen the bills are cards from `components/billing/LumenBillList.tsx`: a search, one-tap filters (All, To receive, GST to pay, Settled, Cancelled, each with its count), a card for each bill with the month it is for, the number, client and case, a bar of how much has come in, what is still to receive and a GST tag; the same bills and the same page opens; above both registers `components/billing/BillFilters.tsx` finds bills by client, case and the month a bill is for, asked of the server and across **every** year unless a year was chosen by hand, and the search box also understands a month typed as "sep", "september 2026", "2026-09" or "09/2026", `billing.month_hint`), `BillEditorPage.tsx` (new and edit: one column of parts, the same in both looks, and `components/billing/BillBar.tsx` kept at the bottom of the screen with the grand total, why it cannot be saved yet, **Preview** (the bill as it will print, large in a window, with Save in it too) and Save; on a screen 1500px wide or more the bill instead sits beside the form in its own pane that stays in view, and there is no Preview button), `BillViewPage.tsx`,
  `components/billing/BillDocument.tsx` (the printed invoice), `BillLinesEditor.tsx` (the lines' boxes and "How the lines are worked out"), `BillPayments.tsx`, `BillTemplateModal.tsx`,
  `BillFontPicker.tsx`, `PrintSheet.tsx`, `billing/billCalc.ts`, `billing/billLayout.ts`, `billing/billFonts.ts`, `billing/rupeeWords.ts`
- api: `routers/billing_router.py`, `billing.py`
- sql: `.cursor/db/migrate_bill.sql`, `migrate_case_transaction_bill.sql`
- tables: `orion_ods.bill`, `bill_version`, `bill_counter`, `bill_profile`; it also writes
  `orion_ods.case_transaction` and reads `case`, `client`

**Rules: the bill.**
- A bill is tagged to a case; its client is the case's client at the time it is saved. `case_code` and
  `client_code` are stored, not names.
- The party name, GSTIN, address and state printed on a bill are a copy held on the bill. They are prefilled
  from the client's `billing_name`, `gstin`, `billing_address` and state, then from the client's last bill.
- **Billing a client group.** When the case's client belongs to a group (another client, `client_group_code`), the bill
  editor offers "The client" or "Client group: X" under the case. Choosing the group replaces the party boxes with the
  group client's own billing details (its `billing_name`, `gstin`, `billing_address` and state, then its last bill), and
  choosing the client puts the client's back; either replaces what was typed. Only what is printed changes: the bill is
  still raised for the case's client (`client_code`), so receivables, reminders and the warehouse follow the client, and the
  choice is not stored (the printed party is the copy). When a bill is edited nothing is chosen until the person picks.
  `billing.list_cases` carries the group's details as `group` (one step up the group chain).
- Numbers are `FY/sequence` (for example `2026-27/202`), one sequence per April-to-March financial year, taken
  from `bill_counter` under a row lock. A number is never changed or reused.
- The server recalculates every figure on save (`compute_bill`): lines are quantity x rate (or by the day or month, below); EPFO, ESIC and
  service charges are percentages of the lines total; GST is on the **taxable value**, which is the lines total plus all of those charges
  (never on the lines total alone); the grand total is
  rounded to the rupee and the difference shown as round-off. `billCalc.ts` repeats this for the live preview.
- **Each bill chooses how its lines are worked out and laid out.** "How the lines are worked out" (in the Lines part of the editor) is
  stored in `bill.line_setup` (`billing.clean_line_setup`, always saved in full) and sets: the **basis** (`unit`: quantity x rate, the
  original; `daily`: rate per day x days; `monthly`: monthly rate x days / days in the month, and a monthly line with no days is the
  whole month); whether the **quantity also multiplies** a day-based amount (off when the quantity is only shown, such as the number of
  persons beside total working days); the **days of the month** a monthly rate is divided by (empty: the real days of the bill's month,
  `billing.days_in_month`); a **total row** under the lines (adds up quantity, days and amount; amounts only, never taxed again); the
  **names of the columns** (Particulars, Qty, Rate, Days, Amount; empty keeps the usual one, and the rate's usual name follows the
  basis); and **extra columns** of the bill's own (at most 5, each with a key `c1`, `c2`… and a name). A line then carries `days`
  (day-based bills only) and `fields` (its value for each extra column, text), both in `bill.lines`. A line's amount is worked out once
  in integers and rounded half up to the paisa, on both sides. A bill with no layout is quantity x rate with the standard columns and
  prints exactly as before. The columns print in this order: particulars, the extra columns, quantity, rate, days, amount
  (`lineColumns` in `billLayout.ts` and `line_columns` in `billing_pdf.py`); hiding "Quantity and rate columns" also hides the days.
  The next bill for a case starts from the case's last bill's layout.
- **Lines can be left out of charges.** With "Some lines are left out of EPFO, ESIC or service charges" ticked (`line_setup.charge_by_line`),
  each line shows what it is part of; a line left out of a charge is listed in `lines[].skip` (`epf`, `esic`, `service`) and its amount is
  not in the base that charge's percentage is taken of. The base is shown under each charge ("on ₹ x of the lines"). Extra charges and GST
  are unchanged: an extra percentage charge is still of the lines total, GST is still on the taxable value.
- **The service charge's basis is chosen per bill.** Under the charges, "Service charge is taken on" is **The lines** (the original: the percentage of
  the lines that are part of it) or **The lines + EPFO + ESIC** (those lines plus the EPFO and ESIC amounts as they stand on the bill, entered or
  calculated). Stored as `line_setup.service_on` (`lines` | `lines_epf_esic`); a bill saved before has none, which is `lines`. The other charges, the extra
  percentage charges and GST are unchanged.
- **Figures can be entered instead of calculated.** Every line amount, and EPFO, ESIC, service charges, CGST and SGST, are calculated by
  default; under each charge, and on each line ("Enter the amount myself"), an amount can be typed instead. It is used as typed and what
  follows is worked out from it (an entered EPFO changes the sub total, the taxable value and the GST). Nothing is refused for not matching:
  the editor warns "This does not match the calculation" and saves it as entered. The bill stores `manual_figures` (`{epf_amount: {value,
  auto}}`, the entered figure and what the calculation gave) and, on a line, `manual` and `auto_amount`; the bill's page lists the
  differences. A line entered by hand needs only a description and an amount (quantity, rate and days become optional; the table then
  prints them empty). A charge with no percentage but an entered amount prints without a rate. The grand total and the round-off are never
  entered. Entered amounts are not carried to the next bill for the case (the lines' left-out charges are). A figure is a paisa amount from
  0 to 1,000 crore.
- **A bill can rename the rows of its totals** ("Wages Total", "EPF", "Total" for the taxable value ...): `line_setup.labels` also takes
  `lines_total`, `sub_total`, `taxable_total`, `epf`, `esic`, `service` (defaults in `SUMMARY_LABELS`, `billLayout.ts`, and `total_lines`).
  The total row under the lines is a tick in the Lines part of the editor.
- **A bill can name its tender.** "Tender ID" and "Tender start date" in Bill details are stored in `bill.tender_id` and
  `bill.tender_start_date` and print under "Your ref." in the invoice box, each with its own tick (`tender_id`, `tender_date` in
  "What shows on the bill"). A new bill starts from the tender of the case's opportunity (`opportunity.tender_id` and
  `opportunity_start_date`, via `case.opportunity_code`), else from the case's last bill.
- **Hindi on the PDF.** Text in Devanagari (a reference number in Hindi, a client's name) is drawn in Mangal (or Noto Sans Devanagari)
  and shaped by `uharfbuzz`, which is a pinned requirement; without that font installed it would print as empty boxes.
- **The two calculations are tested against the same figures.** `backend/tests/bill_vectors.json` holds 97 inputs with the exact
  result for each (real invoices, half-paisa and half-rupee rounding, percentages, extra charges, day-based and monthly lines, every refusal and every limit:
  30 lines, 6 extra charges, quantity 10 lakh, rate ten crore, a percentage of 100.004). The server is tested against it by
  `test_bill_vectors.py` and the preview by `npm run check:bill` (also run by that test, and by CI). A few inputs the two treat
  differently on purpose (a blank rate, a quantity written `1e3`, a `+` sign, a blank percentage) are listed under `differences`,
  each with its reason and both outcomes pinned. The preview refuses what the server would refuse, so a person never sees a total
  they cannot save. Change a calculation or a limit and the vectors in the same change: a changed figure there is a change to what
  people are billed.
- **Each bill chooses its charges.** In the editor's "Charges and tax", EPFO, ESIC, service charges, CGST and SGST
  are rows that can be removed (and added back), and **Add a charge** adds a named charge of the user's own,
  either a percentage of the lines total or a fixed amount (at most 6). A removed standard charge is saved as
  0%, and a charge at 0% is not added and not printed. Named charges are stored in `bill.extra_charges`
  (`label`, `kind`, `value`, `amount`), are added to the taxable value so GST is charged on them, and print
  between the service charges and the taxable value.
- **Each bill chooses what prints.** "What shows on the bill" unticks any part (the PF, ESI, Reg. and other
  numbers, address, the client's GSTIN, "For the month", location, the quantity and rate columns, amount in
  words, the sub total, bank details, terms, the signatures and more; the list is `HIDEABLE` in `billing.py`
  and `billing/billLayout.ts`). The keys of what is left off are stored in `bill.hidden`. A new bill for a case
  starts from the case's last bill, so a vehicle-rental case keeps its choices. The grand total always prints.
  A bill saved before these settings has neither, and prints as it always did.
- **Typeface and text size.** A bill is printed in Arial at 9 pt unless told otherwise. The company sets its own
  typeface and size under Bill template (nine typefaces, 8 to 14 pt; they live in the billing profile as
  `font_family` / `font_size` and are *not* copied into the bill's profile snapshot, so changing them applies to
  every bill that has no choice of its own, issued ones included). One bill can have its own: "Text on the bill"
  in the editor for a new bill, and the same control on the bill's page for an issued one
  (`PUT /billing/bills/{code}/font`, stored in `bill.font_family` / `font_size`; empty follows the company).
  It is how the bill looks, not what it says, so it makes no new version. A size scales the whole bill (text,
  headings, columns, the PDF's table widths) in proportion. `bill_fonts.py` is the catalogue and validation, and
  `billing/billFonts.ts` its copy for the screen (a test compares them). `GET /billing/fonts` lists the typefaces
  this computer can draw in the PDF (a typeface it lacks falls back to Arial there). `get_bill` returns the
  effective choice as `font`. A typeface or size is not
  a change in the Document Center, so it makes **no new version** there: the current version's file is drawn again in the new
  typeface and size and replaces the old one in place (`Filing.look` / `redraw` in `documents_filing.py`; the bill's own choice, else the
  company's; the history records "edited", not a version). This happens when a bill's text is changed, when the company's setting is changed
  (in the background) and at the next filing run. `_bill_content` leaves the typeface out; `_without_font` reads a version filed before that the same way.
- **Each bill can carry its own header details.** "Extra details at the top" adds named values (for example
  Vendor code, MSME No., PO No.; at most 6) that print with the GSTIN and PAN, after the standard ones. They
  are stored in `bill.header_fields` (`label`, `value`), belong to that bill only, and are carried to the next
  bill for the case like the other settings. A detail needs both a name and a value.
- **Each bill can carry extra details of the client.** Under the party address, "Extra client details" adds
  named values (for example State code, a vendor number; at most 6) that print under the client's GSTIN in
  Billed to. They are stored in `bill.party_fields`, are a copy held on the bill like the rest of the party
  details, and are prefilled from the client's last bill, so they follow the client to its other cases.
- The letterhead (`bill_profile`) is copied onto each bill when it is issued, so old bills never change.
- **A bill can print its own company, bank and terms details.** "Company, bank and terms on this bill" (`BillOwnDetails.tsx`) shows the template's
  details as this bill prints them and lets any of them be changed for this bill only: bank, IFSC, account number, signed for, signatory title,
  company name, address, contact numbers, GSTIN, PAN, PF, ESI and registration numbers, and the terms (`PROFILE_BILL_KEYS` in `billing.py`; the
  usual service description and the typeface are not). The change is made on the bill's printed copy (`bill.profile`), so the template and other bills
  do not change, and the PDF, the filed copy and the letterhead version all follow. `bill.profile_overrides` keeps only what differs from the template
  (`apply_profile_edits`), and a repeat bill for the case starts with the last bill's overrides while everything else still follows the template. On an
  edit, only a detail that was changed is applied (a template changed since the bill was issued is not mistaken for an edit), "Use the template's" puts
  one back, and a change to one is a new version.
  To leave a part off altogether, "What shows on the bill" is still the way.
- **Edit** needs a reason, keeps the number, and must stay in the same financial year. The current row is
  copied whole into `bill_version` first, then updated, and `version_no` goes up. An edit that changes nothing
  is refused.
- **Cancel** needs a reason and keeps the number on record. Neither it nor GST paid creates a version.
- **GST is paid to the government in instalments, and recording one is a deliberate act, not a tick** (`billing.record_gst_payment`,
  `reverse_gst_payment`, `components/billing/GstPaid.tsx`): what is still owed and the dashboards' "GST to pay" figures rest on it.
  - *The model.* A bill's GST is **CGST and SGST**, each with its own amount due. A payment is an amount of CGST, of SGST or of both, on a day,
    with an optional challan or payment reference; a bill can have **any number of payments**, so CGST and SGST can be paid on different dates and
    either can be paid in parts. The bill's GST is **Not paid** (nothing yet), **Part paid** (some, not all) or **Paid** (CGST and SGST both covered);
    a bill with no GST shows "No GST". The bill keeps the running total (`gst_paid_amount`) and `gst_paid` (true only when paid in full).
  - *Recording a payment* opens a dialog that names the bill, client, bill date and GST, offers a CGST amount and an SGST amount (each pre-filled with
    what is still to pay, either can be changed or left empty), the **day paid** (not before the bill's date, not in the future) and the reference,
    says what will still be owed afterwards, and needs the tick "I confirm that ₹X of GST for bill N has been paid" before the button (which repeats
    the total) is enabled. An amount over what is left on its component is refused.
  - *Reversing a payment* (from **Payments**, beside the status) shows a red warning of what it undoes, needs **a reason** (at least five
    characters) and the same tick. A reversed payment counts for nothing but **stays in the list**, struck through, with who reversed it, when and why.
  - *The server is the guard, not the screen.* A request must say it was confirmed (`confirm`) and how much GST had been paid when the person opened
    the bill (`seen_paid`). If that has changed since, nothing is written and the answer is 409 ("changed by someone else while you had it open ...
    Reload the bill"), which also stops two quick clicks both writing. The old `POST .../gst-paid` flag endpoint is gone. The bill row is locked
    while it is checked. A cancelled bill has no GST to pay.
  - *It cannot be contradicted.* Editing a bill so that its CGST or SGST falls below what has been paid is refused (reverse the payment first);
    raising it makes the bill Part paid again. A bill with GST paid on it cannot be cancelled until the payments are reversed.
  - *Nothing is ever lost.* Every payment is a row in `orion_ods.bill_gst_payment` (a row per component; rows recorded together share a `batch_id`
    and are reversed together); a reversed row is marked, never deleted. Bills ticked as paid before this existed were converted into the payments
    that tick meant (all the CGST and all the SGST, by whoever ticked it, when), with **no day** ("the day it was paid was not recorded").
  - *Dashboards and the warehouse.* `gst_paid_amount` is in `fact_bill`. "GST not marked paid" / "GST to pay" is what is **still owed** (GST less what
    has been paid), the Paid / Not paid split of GST is in rupees paid and owed, the drill-down shows "GST paid" as Yes / Part paid / No beside a
    "GST to pay" column, and the Billing list's GST column reads Yes / Part / No. The warehouse picks the new column up at its next load.
  - Who may do it is unchanged: anyone with billing write access. Checks: `test_gst_paid.py` (the model, every refusal, conflicts, the edit and cancel
    guards, reversal, the routes, and a round trip against the development database with `ORION_DB_TESTS=1`).

**Rules: revenue and payments.**
- Raising a bill writes one `Prospective` row in `case_transaction` for the bill's case: amount = taxable
  value, GST = CGST + SGST, total = grand total, `transaction_date` = bill date, `bill_code` set.
- **Record payment** takes the cash received, a received date and, if the client paid less because it held something back,
  the **deductions** (see "TDS and other deductions" below). The bill is settled by the cash PLUS the deductions: that whole amount
  is what the payment takes off the bill. The full outstanding amount turns the `Prospective`
  row `Committed`. A smaller amount inserts a new `Committed` row and shrinks the `Prospective` row; taxable
  value and GST are split in the same proportion (`split_payment`).
- So a bill has at most one `Prospective` row (enforced by a partial unique index) and one `Committed` row per
  payment, and they always add up to the grand total.
- `transaction_date` stays the bill date; `received_date` is when the money came in.
- After any payment the bill's total cannot go below the amount received, its case cannot change, and it
  cannot be cancelled. Cancelling an unpaid bill marks its row `Cancelled`.
- Only an admin can reverse a payment. The amount goes back to `Prospective`, and any deduction that came with it is marked
  reversed (the row is kept).
- **A bill or a payment is saved once, however many times the request arrives** (`idempotency.py`, table
  `orion_ods.idempotency_key`). Nothing used to stop a double-click, a retry after a dropped connection or a stale tab from
  sending the same request twice: the second made a second tax invoice with its own legal number, or recorded a repeated *partial*
  payment twice (a repeated full payment was refused only by accident, "received in full"). Now the browser makes a random key when
  a form opens (`api/idempotency.ts`; `crypto.randomUUID` with a fallback, because the office LAN is plain http) and sends it as
  `Idempotency-Key` with creating a bill, editing one and recording a payment. The server **claims the key in the same database
  transaction as the work** (`Idempotency.claim` first, `remember` before the commit): so the key and the work are saved together or
  not at all, a save that fails (a validation error, a crash) leaves the key free for the retry and burns no bill number, and two
  identical requests at the same instant are serialised by the database (the second INSERT waits): exactly one does the work, and the
  other is answered with the first one's bill, marked `Idempotent-Replayed: true`. The same key with something different (another
  amount, another bill) is a 409 with a message to check the list, never mistaken for a repeat; a second real payment of the same
  amount is a new form and has a new key. A repeated edit answers success, not "Nothing on the bill was changed". Keys are kept 30
  days. The bill editor and the payment form also ignore a second click in the same instant (a ref, because the `saving` state is not
  updated until the next render). A request with no key still works but is unprotected, and is logged;
  `ORION_IDEMPOTENCY_REQUIRED=1` refuses it ("This page is out of date. Reload it"), for once no stale tab can still send one. A new
  endpoint that creates a bill, records money or sends something to a client must take a key and claim it in its transaction.
  Tests: `test_idempotency.py` (with `ORION_DB_TESTS=1`: real bills in financial year 2099, a five-way race, partial payments).
- These rows are written only by `billing.py` (`_sync_revenue`, `record_payment`, `reverse_payment`).
  `_sync_revenue` is called after every change to a bill.
- A bill with no case (raised before case tagging) has no revenue row until it is tagged by editing it.

**Depends on.** Operational Data (cases and clients must exist), Sign-in (`billing_access` / `billing_write`, admin).
**Used by.** The Orion dashboards count bill revenue through the warehouse copy of `case_transaction`. The warehouse loads `bill` into
`fact_bill` and links `fact_case_transaction.bill_sk`. Outstanding, Sending and Monthly billing (below) read bills.

---

## Bill numbers and opening things in a new tab

**Does.** A bill number is the same everywhere in Orion. Point at it (or tab to it) and a card says everything about the bill; click it and
the bill opens **in a new tab**, so the screen you were on (its filters, its scroll, what you were reading) is still there. Screens that would
otherwise take you away from where you are, such as a bill opened from a dashboard row, open in a new tab as well.

**Where.**
- api: `billing.bill_card` / `card_from` (the card's content) and `GET /api/billing/card?number=2026-27/202` or `?code=BILL-0012`
  (`routers/billing_router.py`, billing access); `bill_col` in `dashboard/blocks.py`
- ui: `components/billing/BillNumber.tsx` and `BillCardView.tsx`, `billing/billLink.ts` (where a bill is; what text is a bill number),
  `billing/useBillCard.ts` (fetch and a 30-second keep), `hooks/useHoverPanel.ts`, `pages/utility/BillFindPage.tsx`,
  `components/ui/TabLink.tsx`, `navigation/openInNewTab.ts`
- desktop: `desktop/orion_windows.py`, passed to the window by `desktop/app.py` and `desktop/prod_app.py`

**Rules.**
- **The card shows the bill, not a recalculation**: who and what (client, case, reference, GSTIN, description), the first four lines and how many
  there are, every figure as the bill holds it (EPF, ESIC, service charge, named extras, taxable value, CGST, SGST, round off, grand total),
  Paid / Part paid / Unpaid / Cancelled, what was received (the latest three entries) and what is still to come, how many days it has been outstanding,
  whether the GST was paid, who made it and when, and the version and reason if it was edited. It opens after a short pause (so passing along a
  column of numbers does not flash a card for each), stays while the pointer is on it, scrolls inside itself when it is taller than the room, and
  closes on Escape, a click elsewhere or scrolling the page.
- **Where a bill number is drawn this way**: the tables that take a column format (`format: 'bill'` in a dashboard table, a record drill-down
  and a Copilot table; the server marks them with `bill_col` / `"bill"`), the generic record tables (a column named `bill_number`, `bill_no` or
  `bill_code`), the Billing list, Outstanding, Monthly billing, the editor's "copy of bill ..." note, **and any bill number in the text of a
  Copilot answer or a chat message** (`splitBillNumbers`: a financial year, a slash and a sequence; `2026-27/10/05` or `2026-27/202-A` are not
  bills). A new table of bills uses the `bill` format; `test_bill_links.py` lists the existing places.
- **Two ways to the bill**: where the code is known (`bill_code` on a row) the link goes straight to `/utility/billing/<code>`; where only the
  number is known it goes to `/utility/billing/find?number=...`, which finds the bill and shows it (or says there is no such bill). It is an
  ordinary address, so it can be opened in a new tab, copied or middle-clicked before anything has been looked up.
- **Someone without billing access sees the plain number**: no card, no link. The endpoint needs billing access too; the UI hides what the
  server would refuse.
- **New tab, and what it means in the native window.** `TabLink` is a real link (`target="_blank"`, `rel="noopener noreferrer"`). The native
  Orion window (the desktop shortcut) has no tabs, and its window library sends a "new tab" to the system browser (where nobody is signed in) or
  loads it over the current screen, so the launcher gives the page a bridge, `window.pywebview.api.open_window(path)`, which opens a **second Orion
  window** on the same server. All windows of a launch share one profile, so the second window is already signed in (checked with the real window
  library: a cookie set in the first window was present in the second). Only a path inside the app is opened, never another address. Closing the
  second window does not ask "Close Orion?"; the server stops when the last window closes.
- **Which screens open in a new tab**: a bill opened from a dashboard row (`go` in the dashboard shell), "Open this record" in a record
  drill-down, "View load history" on a dashboard, and the links an answer from the Copilot gives (its card links, "View details", links in its text,
  its sources). Moving within a workspace (tabs, Back, save then view, the rail, `Ctrl+K` "Go to", and the Copilot's own "take me there" action,
  which a browser would block as a pop-up because nobody clicked) stays in the same tab.
- **Tally "Document" numbers are not bill numbers** here: they are Tally vouchers, and many (credit notes) have no bill, so they stay plain text.
- Checks: `test_bill_card.py` (the card and its endpoint), `test_bill_links.py` + `npm run check:links` (which text is a bill number, which
  addresses may open, the new-tab logic), `test_desktop_bridge.py`.

## Credit notes and write-offs

**Does.** Corrects what a client owes after a bill was issued: a rate dispute, a short service, a bad debt. A credit note takes money off the part of a bill that
is still to be received, and the revenue and the GST that go with it, **without changing the bill** (its number, its figures and its printout stay as issued).

**Where.**
- ui: `components/billing/CreditNotes.tsx` (the panel on a bill: Issue credit note) and `CreditNoteDialog.tsx` (open one: approve, refuse, withdraw, reverse),
  `pages/utility/CreditNotesPage.tsx` (Utility > Credit notes: every note, with how many wait for a decision)
- api: `routers/credit_notes_router.py` (`/api/credit-notes`: list, `/bill/{code}`, `/preview`, make, approve, reject, withdraw, reverse)
- code: `credit_notes.py` (the only writer of `credit_note` and `credit_note_counter`), `billing.apply_credit` / `unapply_credit` (the only code that moves the
  bill's revenue entry, its `credited_*` figures and its GST when a note takes effect)
- tables: `orion_ods.credit_note`, `credit_note_counter`, and `bill.credited_taxable`, `credited_cgst`, `credited_sgst`, `credited_amount` (`migrate_credit_notes.sql`)

**Rules.**
- **Made, then approved.** Anyone who may change bills makes a note: a kind (Credit note or Bad debt write-off), the amount credited **GST included**, its date (not
  in the future, not before the bill) and a reason. It is **Pending** and changes nothing. The amount cannot be more than is still to be received on the bill (money
  already received is not credited back: a refund is a Bank entry).
- **Who approves.** Someone other than the person who made it, **or an admin** (an admin may approve their own: a team of one still has to be able to issue one). A
  **write-off is approved by an admin only**. Approval needs the confirmation and the amount the person saw (`seen_total`); the server works out who may do what and
  tells the screen (`can_approve`, `can_withdraw`, `can_reverse`). A pending note can be **refused** (with a reason, by anyone who may change bills) or **withdrawn** (by its
  maker or an admin). An approved note can be **reversed** by an admin, with a reason: what it credited is owed again and the GST due goes back up.
- **What approval does**, in one transaction: the bill's open (Prospective) revenue entry shrinks by the credit (and goes when nothing is left), split in the proportions
  of what was open (taxable value, CGST, SGST, the same way a part payment is split); the bill's `credited_*` figures go up; the note gets its number (**`CN 2026-27/1`**,
  from a counter that gives no number twice, so a refused or withdrawn note leaves no gap; the number is kept when the note is reversed). Refused when the bill is
  cancelled or has no case, when less is still to be received than the note says (payments may have come in since it was made), or when more GST has already been paid
  to the government than the bill's GST would then come to (reverse that GST payment first, on the bill's GST).
- **A bill with an approved credit note cannot be cancelled**, and cannot be edited below what was credited (`billing.update_bill`, `_sync_revenue`). Its status reads
  **Settled** (not Paid) when received plus credited cover it.
- **Everything that reads what a client owes follows**: the bill's Billed / Credited / Received / Still to receive figures, the bill list's balance, Outstanding
  (`receivables.py`), the bill card, the GST due on the bill (`billing._gst_due`), the Bank forecast's GST still to pay (`bank_expected`), the dashboards' revenue, billed,
  GST and open amounts (`fact_bill.credited_*`, after the next warehouse load; see "Orion dashboards") and Utility > GST (the GST on a credit note comes off in the month of the note).
- A credit note is kept for ever; once decided it never changes (a trigger refuses a delete or a change other than the decision and the reversal).
- **Not done:** a printable credit note, filing it in the Document Center, a refund of money already received, and credit notes against a bill that has no case.

**Depends on.** Billing (`billing_access` to read, `billing_write` to make and decide, admin for a write-off and a reversal), the bill's revenue entries.

## GST position and input tax credit

**Does.** Sets the GST Orion owes on its bills against the GST its suppliers charged on its costs. An expense that has GST must carry the **supplier's GSTIN
and invoice number** (the credit can be claimed only against them); Utility > GST then shows, month by month of a financial year, the GST on the bills, the
input tax credit, the net to pay (a month with more credit than tax is a credit carried forward) and the GST payments recorded on bills.

**Where.**
- ui: `pages/utility/GstPage.tsx` (Utility > GST); the Supplier GSTIN and Supplier Invoice No fields on the Expense Transaction form and Excel template
- api: `routers/gst_router.py` (`GET /api/gst/position?fy=`), `routers/entities_router.py` (the expense form)
- code: `gst_position.py` (the figures), `gstin.py` (shape and check digit), `entities._itc_problem` / `invalid_reason` (the rule)
- tables: `orion_ods.expense_transaction.vendor_gstin` and `vendor_invoice_no` (`migrate_input_tax_credit.sql`); `fact_expense_transaction` carries both

**Rules.**
- **An expense with GST (above 0, not cancelled) needs both the GSTIN and the invoice number**, whether it is typed, uploaded or entered by the Copilot. A
  supplier that is not registered charges no GST: enter the amount with none. The GSTIN is tidied (capitals, no spaces) and its **check digit is verified**, so a
  mistyped number is refused when it is entered.
- **An expense stored before this keeps its place**: it can be corrected for something else without a GSTIN, but the moment its GST is changed (or a supplier
  detail is given) it meets the rule. The database does not enforce it (the columns are optional), so an old row never blocks a save.
- Output GST is CGST + SGST on issued bills, by the bill's date, **less the GST on approved credit notes in the month of the note** (a note adjusts the tax when it is
  issued, not in the month of its bill). Credit is the GST on expenses that are Incurred, have both supplier details and fall in the
  month of their transaction date. Planned (not yet incurred) and cancelled costs are not credit. GST paid is the non-reversed GST payments on bills, by the day
  they were paid.
- **A warning** says how many incurred costs carry GST but no supplier details (their GST is not counted as credit).
- **Not modelled:** the return period and its filing (GSTR-3B), reverse charge, blocked credits (for example motor cars), the supplier's own filing, TCS, late
  fees. The **Bank forecast still expects the full GST on bills**; it does not net out the credit.

**Depends on.** Billing (`billing_access`), Expense Transaction.

## EPFO and ESIC paid on a bill

**Does.** A bill charges the client for EPFO and ESIC (percentages of the lines, or amounts entered). The business pays those amounts over to the authorities, in whole
or in parts, on different days, and needs to know **which bills it has paid them for**, the same as it does for GST. Each bill shows where its EPFO and its ESIC stand
(Not paid, Part paid, Paid), records the payments, and the Bank, the dashboards and a monthly page follow them.

**Where.** api: `billing.py` (`record_statutory_payment`, `reverse_statutory_payment`, `statutory_summary`, `_sync_statutory`), `routers/billing_router.py`
(`POST /billing/bills/{code}/statutory-payments` and `.../{batch}/reverse`), `statutory_position.py` + `routers/statutory_router.py` (`GET /statutory/position`). sql:
`migrate_bill_statutory.sql` (the table `bill_statutory_payment` and the running totals `bill.epf_paid_amount` / `esic_paid_amount`), the bank view and `account_id` in `migrate_bank.sql`, four
columns of `orion_dw.fact_bill` in `dw_schema.sql`. ui: `components/billing/StatutoryPaid.tsx` (on the bill's page, Classic and Lumen), `pages/utility/StatutoryPage.tsx` (Utility >
EPFO and ESIC), the register's two columns and the Lumen badge, the bill card, the Controls dashboard. tests: `test_statutory_paid.py`.

**Rules.**
- **Charged is revenue; paid is a cost, independent of salary.** EPFO and ESIC are **inside a bill's taxable value** (lines + EPFO + ESIC + service charge + extras), so they are inside Revenue,
  Billed and the base GST is charged on. Recording a payment does not change Revenue. It makes a **cost** of that amount **on the day it was paid**, against the bill's case and client: Expense and
  Operating margin on every dashboard, by month, case, client and domain, go down by it, and a reversal gives it back. It does not depend on payroll or attendance being entered, and salary is
  its own cost: the two are not linked and nothing is counted twice. It is done in one place, the warehouse view `orion_dw.expense_cost` (the expenses plus the payments not reversed), which
  the dashboards' expense scope reads; the cost appears as the expense type "EPFO and ESIC paid". It is not an Expense entered by hand, so nothing is entered twice and the Bank has it once. The cost
  is counted when PAID, as Orion counts other expenses (`PaidEpfoAndEsicIsACost`, `test_profit_and_loss.py`).
- **What is due is what the bill charged** (`epf_amount`, `esic_amount`). A credit note does not lower it: what is owed to the authorities follows the wages worked, not the bill's value.
- **A payment is a deliberate act, as for GST.** It needs the confirmation, the day (not before the bill, not in the future), the amounts (each no more than is still to pay), an optional challan
  or reference, the account it was paid from, and the amount paid that the person saw (`seen_paid`): if anyone changed the payments since, nothing is written and the screen says so (409). Reversing
  one (everything recorded together) needs a reason and keeps the row, marked reversed, with who and why. Nothing is ever deleted.
- **A bill with EPFO or ESIC paid on it cannot be cancelled** until the payments are reversed, and **an edit cannot take what a bill charges below what has been paid** (`_sync_statutory`, in
  the same transaction as the edit, like `_sync_gst`).
- **The Bank.** A payment is money out on the day it was paid (the view `bank_movement`, source `statutory`, category "EPFO / ESIC paid on a bill"), from the account named. A payment recorded on a bill
  must **not** also be typed in as a manual bank entry (that entry category now says "not recorded on a bill"). A payment reversed leaves the bank by itself, and a statement line matched to it is
  returned to the exceptions list.
- **The dashboards** (Controls tab; the warehouse is at most an hour behind): **EPFO not marked paid** and **ESIC not marked paid** (what issued bills charged less what has been paid, never below zero per
  bill), a chart of that by the age of the bill, the list of bills to pay, a finding ("₹ of EPFO and ₹ of ESIC charged on bills has not been marked as paid"), and drill-through to the bills
  (`epf_charged`, `epf_left`, `esic_charged`, `esic_left` columns). `fact_bill` carries `epf_amount`, `esic_amount`, `epf_paid_amount` and `esic_paid_amount`; when the columns were added, the current
  rows were backfilled once so the first load did not write a new version of every bill.
- **Utility > EPFO and ESIC** shows, for a financial year, what bills charged and what was paid by month, and what is still to pay over **all** bills (a bill can be paid in a later year), with the oldest
  bills first. Opening a bill from it is where the payment is recorded.
- The register has "EPFO paid" and "ESIC paid" (Yes, Part, No, or a dash where the bill charged none), the Lumen card a badge, and the bill's hover card a row.

**Not done.** Making the challan or the return (ECR, ESIC contribution file): those are on the EPFO and ESIC portals. Paying one challan across many bills at once (each bill is recorded on its own).
Forecasting the dues in the Bank's look-ahead. Working the amounts out from attendance or salary (they are what the bills charged).

**Depends on.** Billing (`billing_access` to see, `billing_write` to record or reverse), the Bank (`bank_movement`), the warehouse (`fact_bill`). **Used by.** The Bank ledger, the Controls dashboard, the Copilot's dashboard answers.

---

## TDS and other deductions

**Does.** A client usually pays a bill net of TDS, and sometimes holds back a penalty or a few rupees of rounding. Without a way to say so, the
difference stayed "outstanding" for ever (a false overdue bill, a wrong balance, no record of the tax credit). The payment form now takes **the cash
that came in** and, optionally, **what was held back**, and the bill is settled by the two together.

**Where.**
- ui: `components/billing/BillPayments.tsx` (the payment form: "Held back by the client", with TDS deducted / Penalty / Rounding / Other),
  `pages/utility/TdsPage.tsx` (Utility > TDS)
- api: `routers/billing_router.py` (`POST /billing/bills/{code}/payments` with `deductions`), `routers/tds_router.py` (`/tds/ledger`,
  `/tds/suggestion`, `PUT /tds/deductions/{id}/matched`)
- code: `billing.record_payment` / `reverse_payment` / `clean_deductions` (the only writer of `bill_payment_deduction`), `tds.py`
- tables: `orion_ods.bill_payment_deduction` (`migrate_deductions.sql`); the view `bank_movement` (`migrate_bank.sql`)

**Rules.**
- **The revenue entry holds the whole amount settled** (cash plus deductions), so a bill's entries still add up to its grand total and the revenue
  in the dashboards does not shrink by the TDS; **the bank sees only the cash** (the view subtracts the deductions that are not reversed). A statement
  line is matched to that cash. A bill paid net of TDS is *Paid* and leaves Outstanding.
- A deduction has a kind: **TDS** (needs its section, for example 194C; the rate is optional), **Penalty** and **Other** (need a reason) and
  **Rounding** (at most ₹ 10). At most 6 per payment. TDS of more than a fifth of what the payment settles is refused as a typing mistake. The cash and the
  deductions together cannot be more than is still to be received, and the cash must be over nothing.
- A deduction is **kept for ever** and never changes (a trigger refuses a delete and any change but a reversal or the 26AS tick). Reversing the payment
  reverses its deductions (`reversal_reason`) and leaves the rows. The payment form keeps one `Idempotency-Key`, and the deductions are part of its fingerprint.
- **TDS is not a cost; the rest is.** TDS is tax already paid on the company's behalf and is claimed back, so it never touches Revenue or Margin. A **penalty**, a short
  payment (**Other**) and **rounding** are money the bill was for and will never come: each is a **cost on the day of the payment**, against the bill's case and client, and lowers
  Expense and Operating margin on every dashboard (expense type "Penalties and short payments"). Revenue stays the whole bill. It is done in the warehouse view
  `orion_dw.expense_cost` (the same one EPFO and ESIC paid go through); a deduction reversed with its payment takes its cost away. It is not typed as an Expense
  (that would count it twice). `ShortfallIsACostEverywhereTheCostIsRead` and `PaymentWithDeductionsTests` pin it down.
- **The form suggests, the person decides.** Adding TDS fills the section and rate this client was last deducted under (else 194C at 2%) and an amount
  of that rate on the taxable value of what is still to be received; the cash follows (the amount left) until it is typed. Only what the client actually held
  back is recorded.
- **Utility > TDS** lists every TDS deduction not reversed, by financial year (of the payment's date), client, income-tax quarter (Q1 April-June) and
  whether it has been found in the client's **Form 26AS**, with totals and an export. A row is opened to tick it as found (with the certificate or
  26AS reference) or take the tick off; this is the only thing written there (`matched_26as_*`). Claiming the credit in the return is outside Orion.
- **The Orion dashboards carry it**: Cash collected is what reached the bank (the entry less the deduction), TDS held back is its own figure, and the collection rate counts
  cash plus what was held back (see "Orion dashboards"). Credit notes against a bill are a separate feature.

**Depends on.** Billing (`billing_access` to read, `billing_write` to record and to tick), the Bank views.

## Outstanding and reminders

**Does.** Shows what each client still owes on issued bills, split by the age of each bill (0–30, 31–60, 61–90
and over 90 days), with the bills behind each client's total. A reminder, by email or WhatsApp, carries a
statement of the client's unpaid bills. The statement can also be downloaded as a PDF.

**Where.**
- ui: `pages/utility/ReceivablesPage.tsx` (Utility > Outstanding), `components/billing/ShareModal.tsx`
- api: `routers/billing_router.py` (`/billing/receivables...`), `receivables.py`, `billing_pdf.py`
- tables: reads `orion_ods.bill`, `case_transaction`; writes `orion_ods.bill_message`

**Rules.**
- What is owed on a bill is its grand total less its `Committed` revenue entries, the same figure the Bills
  register calls "To receive". Nothing here works out money of its own.
- Age is counted from the **bill date** to today, not from a due date. A bill is in exactly one bucket.
- Only issued bills tagged to a case count. An issued bill with no case has no revenue entries, so there is no
  record of whether it was paid; those are counted and shown as a note, never reported as owed.
- A reminder covers every unpaid bill the client has. It is recorded in `bill_message` with the bills it
  covered, which gives "last reminder" per bill and per client. Opening WhatsApp is recorded the same way as a
  sent email: Orion cannot know whether the message was actually sent from WhatsApp.
- Viewing needs ODS access; sending a reminder needs ODS write.

---

## Sending a bill

**Does.** From a bill's page: download the invoice as a PDF, or send it to the client by email (PDF attached) or
WhatsApp.

**Where.**
- ui: `pages/utility/BillViewPage.tsx`, `components/billing/ShareModal.tsx`
- api: `routers/billing_router.py` (`/billing/bills/{id}/pdf`, `/share`, `/email`, `/whatsapp`), `receivables.py`,
  `billing_pdf.py`, `mail.py`
- tables: writes `orion_ods.bill_message`

**Rules.**
- The PDF is drawn on the server by `billing_pdf.invoice_pdf` from the stored bill and the company details copied
  onto it, so it never differs from what was issued. It can be drawn on the company letterhead instead of with
  its own typed heading (see Letterhead). It follows `BillDocument.tsx` section by section but is written
  separately: a change to what the printed bill shows has to be made in both. So is a change to its sizes: the
  screen draws every size in `em` of the bill's base size and the PDF multiplies its sizes and widths by size / 9,
  so a new size or column has to scale in both (`test_bill_fonts.py` fails on a pixel size in `BillDocument.tsx`).
- Email is sent by the server through `mail.send_mail` and needs `ORION_SMTP_HOST`. Without it the dialog says
  so and the PDF can still be downloaded. Replies go to the sending user's own email address when they have one.
- WhatsApp cannot take an attachment from a link. Orion opens `wa.me` with the message ready; the PDF is
  downloaded from the same dialog and attached by hand. A ten-digit number is taken as an Indian mobile.
- A cancelled bill cannot be sent. Each dialog starts with the address or number last used for that client.
- The message wording is built in `receivables.py` and can be edited before sending.

---

## Monthly billing

**Does.** Lists the cases that were billed before but have no bill yet for a chosen month (last month by
default), and opens the bill editor filled in from the case's last bill. The same copy is available on any bill
as "Copy as new bill".

**Where.**
- ui: `pages/utility/DueToBillPage.tsx` (Utility > Monthly billing; in Lumen the month is a job to get through: `components/billing/LumenDue.tsx`, a month stepper, a hero saying how many cases are still to bill, about what they come to and how far along the month is, "behind by over a month" chips, and a card per case with a "Copy last bill" button; the same cases and the same copy), `BillEditorPage.tsx` (`?from=<bill>&month=YYYY-MM`)
- api: `routers/billing_router.py` (`/billing/due`), `billing.list_due_to_bill` (answers `month`, `cases` and `billed`: how many cases already have an Issued bill for the month and what they came to, for the progress bar)

**Rules.**
- A copy takes the party, location, description, reference, lines and percentages from the source bill. The
  letterhead and bill date are today's, and the month moves on. Nothing is saved until the user issues it, so a
  copy takes a bill number only when issued.
- Nothing is issued automatically: manpower quantities change month to month, and an issued number is never
  reused, so a wrong automatic bill would have to be cancelled and would leave a gap on record.
- A case is listed when its latest issued bill is for an earlier month than the one chosen, within the last six
  months, and the case is not Inactive.

---

## Letterhead

**Does.** Puts anything onto the company letterhead: letters, quotations, notices and certificates typed in
Orion and kept; PDFs made elsewhere (Word, Excel, Tally, a scan); blank letterhead paper; and, from Billing, a
bill or a client's statement. The letterhead's header and footer can be replaced and moved by an admin.

**Where.**
- ui: `pages/letterhead/LetterheadPage.tsx` (the three tabs), `LettersPage.tsx` (list and starting points; in Lumen "What do you want to write?" with a card for each starting point and one for putting a PDF on the letterhead, then the saved letters as searchable cards: `components/letterhead/lumenLetters.tsx`),
  `LetterEditorPage.tsx` (in Lumen the letter's name is typed in a bar that stays at the top with Save and Print; the side panel is "About this letter"), `StampPdfPage.tsx`, `LetterheadDesignPage.tsx`;
  `components/letterhead/LetterheadSheet.tsx` (the page on screen, the print, and the shared design),
  `LetterToolbar.tsx`, `richText.ts` (editing commands, tidying pasted text), `templates.ts` (starting text);
  `components/ui/PdfPreview.tsx`; `components/billing/letterheadChoice.ts`; the `lh-*` rules in `index.css`
- api: `routers/letterhead_router.py` (`/api/letterhead/design`, `/design/{part}`, `/letters`, `/stamp`, `/blank.pdf`),
  `letterhead.py` (the design, letters, cleaning a letter's text), `letterhead_page.py` (drawing the letterhead on a
  PDF page), `letterhead_pdf.py` (stamping an uploaded PDF, blank paper); `billing_pdf.py` and `receivables.py` for
  bills and statements
- assets: `backend/app/assets/letterhead/header.jpg`, `footer.jpg` (the letterhead shipped with the application)
- sql: `.cursor/db/migrate_letterhead.sql`
- tables: `orion_ods.letter`, `orion_ods.letterhead_design` (one row, absent until the letterhead is changed)

**Rules: the letterhead.**
- It is two picture strips, a header and a footer, across an A4 page. A strip always spans the page between the side
  gaps and keeps its own proportions, so its height follows from its picture. The words inside a strip are part of
  the picture: changing the address means uploading a new strip.
- Until an admin replaces a strip, the one in `backend/app/assets/letterhead` is used, so a new database prints the
  standard letterhead with no row in `letterhead_design` (nothing is seeded). A replacement is stored in that table,
  in the database, so it is in every backup and is the same in dev and prod only if uploaded to each.
- A replacement must be a JPG or PNG, at least 600 px wide, at least twice as wide as tall, up to 8 MB. Transparency
  is flattened onto white and anything wider than 3,000 px is made smaller (`letterhead.prepare_image`).
- Seven lengths in millimetres place everything (`letterhead.SETTING_LIMITS`: the gap above the header, below the
  footer and beside both; the gap between each strip and the text; the left and right text margins). Each is held
  within its limits on save.
- **One place works out where things sit**: `letterhead.layout`, sent to the browser as `design.layout`. The screen
  and the print use those numbers; the PDFs use `letterhead_page.Letterhead.boxes`. A test holds the two together.
- Seeing the letterhead needs Letterhead or Billing access (a bill can be printed on it); changing it needs the
  `admin` role, because the change shows on everything printed afterwards. `version` goes up on every change and is
  in each image's address, so browsers fetch the new picture.

**Rules: letters.**
- A letter is typed on a page that looks like the printed one, and the same HTML is what prints. Printing is the
  browser's (`window.print`): `LetterheadPrint` puts the strips in as fixed elements, which a browser repeats on every
  page, and the text in a table whose header and footer rows are empty spacers of the strips' height, also repeated,
  so text on any page stays clear of both. The page margin is set to zero for that print and put back after. Saving as
  a PDF is the print dialog's "Save as PDF". There is no server-drawn letter, so any language the browser can show
  prints correctly.
- **The body is rebuilt on the server before it is stored** (`letterhead.clean_html`): only the tags the editor makes
  are kept (paragraphs, two headings, bold, italic, underline, lists, tables, line, line break), with text alignment,
  cell spans and the page-break mark as the only attributes. Scripts, styles, links, images, classes and event
  handlers are dropped; the words are kept. Another user's browser draws this HTML, so nothing else may get in.
  `richText.ts` tidies pasted text with the same list, and a test fails if the two lists differ.
- A letter has a name (required, for the list), a date and an optional reference number. These are for finding it;
  they print only where they are typed in the letter. It also keeps its font (Arial or Times New Roman), text size
  (8 to 16 pt) and whether the header and the footer are printed.
- Unticking the header and footer prints on paper that already has the letterhead: the text keeps its place and the
  space is left blank. On screen a strip that will not print is shown faintly.
- New documents start from text in `templates.ts` (letter, quotation, certificate, blank). They are starting text,
  not stored templates.
- A letter can be copied, and deleted. Deleting is permanent; there is no version history for letters.

**Rules: PDFs.**
- **Stamping** takes a PDF up to 25 MB and 300 pages and returns it with the strips on its pages. "Shrink to fit" (the
  default) first makes each page smaller so all of it sits between the strips; "Keep full size" lays the strips over
  the page as it is. The letterhead can go on every page or only the first, with the header, the footer or both.
  Pages keep their own size and direction. Nothing is stored: the file comes in and the stamped file goes out. A
  password-locked or unreadable PDF is refused with the reason.
- **Blank letterhead paper** is an A4 PDF of 1 to 50 pages.
- **Bills and statements**: `GET /billing/bills/{id}/pdf` and `/billing/receivables/{client}/statement.pdf` take
  `?letterhead=true`, and the two email routes take `letterhead` in their body. On the letterhead the typed company
  name, address, contact and registration numbers are left off, because the letterhead carries them; the bill's own
  header details, and everything else, are unchanged. A bill keeps a smaller gap beside each strip than a letter
  (`billing_pdf.BILL_GAP_MM`). "Use the company letterhead" on a bill, and "Statements on the company letterhead" on
  Outstanding, switch Print, Download PDF and Send over; the choice is remembered in that browser. With it on, Print
  opens the PDF in the page (`PdfPreview`), whose own toolbar prints it. The bill on screen, and the bill printed
  without the letterhead, are unchanged.
- A PDF made by the server is shown in the browser's own PDF viewer inside the page. The desktop windows show it the
  same way.

**Depends on.** Sign-in (`letterhead_access` to read, print and stamp; `letterhead_write` to write, edit and delete
letters; `admin` to change the letterhead). Billing uses it for bills and statements.
**Used by.** Billing (bill and statement PDFs, emailed PDFs).

---

## PDF tools

**Does.** Everyday jobs on PDFs, in the style of iLovePDF, for the files the company sends and files: **merge** several PDFs into one,
**split** one into several (a ZIP), **extract** or **remove** pages, **reorder** pages (a page can come twice, a blank page can be added, or the
whole PDF reversed), **rotate**, **resize** pages to A3, A4, A5, Letter or Legal, make a PDF from **pictures** (JPG, PNG, WebP, GIF, BMP, TIFF,
HEIC from a phone) and take the **pictures out of** a PDF, read its **text**, **compress** it, **repair** a damaged one, **lock** it with a
password or **unlock** one, put a **watermark** or **page numbers** on it, and **edit its details** (title, author, subject, keywords) or clear
them. "Put a PDF on the letterhead" is the same kind of tool and keeps its own place in Letterhead; the home screen points to it.

**Where.** api: `routers/pdf_tools_router.py` (`/api/pdf-tools`), `pdf_tools.py` (the tools; pure Python, bytes in and bytes out),
`request_limits.py` (the upload size guard). ui: `pages/pdftools/` (`PdfToolsPage` the shell, `PdfToolsHome` the tool grid, `PdfToolPage` one tool,
`tools.ts` what each tool is, asks and needs, `FileList`, `OptionFields`, `ResultCard`), the rail item "PDF tools" (`components/nav/navigation.ts`),
`pdfToolsRouteTree` in `workspaceRoutes.tsx`. tests: `test_pdf_tools.py`.

**Rules.**
- **Nothing is stored.** The files are read into memory, worked on and forgotten with the answer. No file, result or password is written to disk or
  to the database, and the log line for a job says who, which tool and how many bytes: never a file name, a password or anything from inside a
  file. A browser keeps the result only until the person leaves the screen.
- **Who may use it:** the people who may use the Letterhead (`letterhead_access`; the tools change nothing in Orion, so there is no write flag).
  Every route has `require_letterhead`; `test_pdf_tools.py` checks the guard on each, signed out and without access.
- **Limits** (`pdf_tools.py`, and sent to the screen by `GET /pdf-tools/limits`): 40 MB a file, 120 MB and 40 files a job, 1,500 pages in a file and
  in what comes out, 500 files in a ZIP, 60 million pixels in a picture. The upload is also refused by `RequestSizeLimitMiddleware` before the framework has
  written it all to disk (by its declared length, and as it arrives for one that does not declare it): 413 with a plain message. At most three jobs run at
  once; a fourth that cannot get a place within 20 seconds is told, with a 503, to try again in a minute.
- **Pages** are written in one small language (`pdf_tools.parse_pages`): `1-3, 5, 8-` (a range, one page, from 8 to the end), `-3` (the first three), `last`,
  `5-last`, `odd`, `even`, and a range written backwards (`5-1`) comes out reversed. A page that is not there, or something that is not a page, is refused
  in words ("Page 9 does not exist: Invoice.pdf has 3 pages").
- **Locked PDFs.** A PDF that needs a password is shown as locked and asks for it on the screen; with it, every tool works on the file and the result is not
  locked. **Orion never guesses or breaks a password**: Unlock is for someone who knows it (or for a PDF that only restricts printing or editing, which opens with
  no password and comes out without the restriction). Lock uses AES-256 (`cryptography`) with a password of at least 4 characters, optional printing, copying and editing
  switches and an optional separate owner password.
- **Merge** takes the files in the order shown (drag, or the arrows), can take only some pages of each, and by default adds a bookmark for each file.
  **Split** is by ranges (each comma-separated part is a file), every N pages, or a file a page. A file that cannot be split says so.
- **Pictures to PDF** puts a photo in as it is (a JPEG is not re-encoded, and is not made a quarter bigger by text encoding, which reportlab does unless
  `_binary_images` turns it off), turns a photo taken sideways upright, puts transparency on white, and can use A4, Letter or the picture's own size.
  **Compress**: Light only tidies the file; Recommended and Strong also make the pictures inside lighter; a file that cannot get smaller comes back as it was, with a note.
- **Not done on purpose:** turning a page into a picture (that needs a rendering engine, which would run untrusted files in native code inside the server and
  could stop it), reading text from a scan (no OCR), and Word or Excel conversions.
- **Carry on.** A result that is a PDF can be passed to another tool from its result card ("Carry on with this file in…"): the file goes to that tool only
  (a screen being left must not keep it), and it is the first file there.
- A damaged file is a plain refusal that points to Repair, never a crash: a file with a PDF header and nothing else, a cut-off file and a bad index are all tested.

**Depends on.** Sign-in (`letterhead_access`); `pypdf` and `cryptography` (reading and writing PDFs, AES), `reportlab` (watermarks, numbers, pictures), `Pillow` and
`pillow-heif` (pictures), `billing_pdf.fonts()` for the face a watermark or number is drawn in (and the Hindi face for Devanagari text).
**Used by.** Nothing: it is a tool people open. The screens call only `api.pdfToolLimits`, `api.pdfInspect` and `api.pdfTool`.

---

## SQL editor

**Does.** Lets an administrator look into the database and ask it questions, the way SSMS or pgAdmin does: the database as a tree, a query editor, results in a grid, saved queries,
the history of what was run, and views. It is Data > SQL editor (`/sql`), for **admins only**.

**Where.**
- ui: `pages/sql/SqlEditorPage.tsx` (the page), `components/sql/` (`SqlCodeEditor.tsx` CodeMirror with PostgreSQL highlighting and autocomplete of Orion's own tables and
  columns, `SqlResultGrid.tsx`, `SchemaTree.tsx`, `ObjectDetailModal.tsx`, `SqlSidePanels.tsx` saved queries, history and the save dialog)
- api: `routers/sql_router.py` (`/api/sql/...`), `sql_lab.py` (running, catalog, saved queries, history), `sql_guard.py` (what may run)
- sql: `.cursor/db/migrate_sql_lab.sql`; tables `orion_ods.sql_saved_query`, `orion_ods.sql_query_log`, the schema `reports` and the view `reports.users`

**What it has.** The tree lists the schemas with their tables, views and functions, row estimates and sizes, and each table's columns with primary and foreign keys; right-click gives
Select top 100, Count, an INSERT or UPDATE to fill in, the table's structure (columns, keys and who points at it, indexes, triggers, statistics, a CREATE statement), and Copy name. Editor
tabs (kept in the browser), Run (the selection, or everything: Ctrl+Enter) and Run statement (Ctrl+Shift+Enter), several statements at once (a result for each), Explain and Analyze (the plan is shown as text),
Format (Ctrl+Shift+F), Cancel (stops the query in the database), a row limit (100 to 10,000) and a time limit (up to two minutes). Results: types in the header, sort, a funnel filter on every
column (the same as on the data tables), search, paging, copy (all, or a cell with Ctrl+C), CSV of what is shown or of up to 100,000 rows from the server, a row opened in a panel, messages with an error's line
and a "Go to" link. **Save** keeps a query (a title, a folder, a note, optionally shared with the other admins, who can run and copy it); **History** lists every run, yours or everyone's.
**Save as view** writes `CREATE OR REPLACE VIEW reports.name AS …` (or a materialized view, or a table of the rows) in a new tab.

**Rules** (`sql_guard.py`, tested in `test_sql_editor.py`).
- **Who and when.** Admins only (`sql_lab.can_use`, a `require_sql` on every route; the page id `sql`). `ORION_SQL_EDITOR` is `off`, `readonly` or `full`; unset, a development computer is `full` and
  **production is `readonly`**: changes from the editor on the office PC are switched on deliberately in its `.env`.
- **Reading** runs in a read-only transaction that is rolled back, with a time limit, on every table except the private ones: passwords and reset tokens (`app_user`), sessions, sign-up requests, Google's token, idempotency keys and people's
  messages (`chat_*`, the Copilot's conversations) are never readable. `reports.users` is the safe view of the users.
- **Changes** need "Allow changes" (and `full`): INSERT, UPDATE, DELETE in a transaction that is **rolled back after the run unless "Roll back after running" is unticked**. The tables Orion's own code owns (bills and their money, the
  bank, documents, attendance, the schema record and the editor's own tables: `OWNED_TABLES`) can be read but are changed only through the application (AGENTS.md "Data ownership"). An UPDATE or DELETE with no WHERE, a DROP and a TRUNCATE are confirmed first.
- **Structure** (CREATE TABLE/VIEW/MATERIALIZED VIEW/INDEX/SEQUENCE, ALTER, DROP, TRUNCATE, COMMENT, REFRESH) only in the `reports` schema; Orion's own schemas change through the schema files and `app.migrate`. Not offered at all: roles, grants, SET, COPY, DO,
  functions, schemas, extensions, transaction control (each run is one transaction), `nextval` (it would use up a bill number), and the functions that reach outside the database or other people's sessions.
- **Audit.** Every run, refused or failed too, is a row in `sql_query_log` (who, what, mode, how it ended, rows, time); the editor cannot change it. All of this is a guard against mistakes, not against a determined administrator: the real protection is that only
  admins reach it and that it is recorded.

---

## Column filters

**Does.** Every column of the tables that list data has a funnel in its header. It opens a small panel with two ways to filter that column: a **condition** (text: contains,
does not contain, is, is not, starts with, ends with, is empty, is not empty; numbers and dates: equals, is not, more than, at least, less than, at most, between, is empty, is
not empty) or a **pick of values** (the values the column holds, most common first, with how many rows each is on, and a box to find one). The filters on are shown as chips
above the table, each removed with its ×, and combine (every one must hold, together with the search box). Enter applies.

**Where.**
- *Orion data, Tally data and the two warehouses* (`components/PreviewRecords.tsx` over `ui/DataTable.tsx`): the **server** filters the whole table, not the rows on screen. The filters
  travel as JSON in `?f=` on `/{name}/preview`, `/{name}/export` (the Excel download holds only what the filters leave) and `/{name}/values` (the pick list: it counts the rows the search and the
  *other* columns' filters leave). `column_filters.py` reads and checks them; `db_utils.fetch_preview_ex` / `fetch_column_values` put them in the SQL. What a column holds (text,
  number, date, bool) comes from its database type, and the preview answers it as `kinds`.
- *Every table on the dashboards* (`components/dashboard/ReportTable.tsx`): the rows are already in the page, so they are filtered there (`tables/columnFilter.ts`); the pick list is made from
  those rows. Totals become a subtotal of the rows left, as they do for the search box, and only when the list is not capped. Money, counts and percentages take number conditions; text and bill
  numbers take text conditions and a pick.
- *The records behind a figure* (`components/dashboard/RecordTable.tsx`, Orion and Tally): the **server** filters (`?f=` on `/dashboard/records/{dataset}` and `/tally-dashboard/records/{dataset}`),
  conditions only (no pick list). A ledger snapshot set (worked out in Python) says `filterable: false` and shows no funnels.
- *The Users and sign-up tables on Admin*: in the page (`DataTable filterable`).
- Not covered: the compact two-or-three-row summaries (`DataGrid`), and the screens that have their own purpose-built filters (the Bank ledger, payables, payroll, receivables, attendance, the
  bill register's tabs, Documents). A filter on a column that is not there, or an operator the column cannot answer, is a 400 with a sentence, never a 500.

**Rules.** A value from the request is always a SQL *parameter*: only the table's own column expressions are ever written into the SQL (`column_filters.build`), an operator must be one of
`column_filters.OPS` for the column's kind, numbers and dates are converted before they reach the database, a column's private fields stay private (the preview's source already leaves them out,
so a filter on one is "no such column"), and at most 20 filters of 200 values are accepted. The operators are written twice, in `column_filters.py` and `tables/columnFilter.ts` (`test_column_filters.py` compares them;
`npm run check:filters` checks the browser's side).

---

## Document Center

**Does.** Keeps the company's documents and each case's and client's: tenders, work orders, contracts,
guarantees, insurance, licences, registrations, policies. Every document has a title, a kind, tags, a status
(Draft, Active, Superseded, Archived), a document date, an optional expiry date with a reminder, and any number of
versions. People find documents by browsing (the company, a case, a client, folders) or by searching titles, tags, file
names and the words inside PDF, Word, Excel, PowerPoint and text files. It is Utilities > Documents (`/documents`).

**Where.**
- ui: `pages/documents/DocumentCenterPage.tsx` (the whole screen; where you are, the view and every filter live in the address,
  including the open document `?doc=`), `components/documents/` (`ExplorerTree.tsx` the folders on the left, `ExplorerList.tsx` the list
  and icons with selection, rename, drag and drop, `explorerUi.tsx` icons and the right-click menu, `FolderPicker.tsx` choosing a folder,
  `Overview.tsx` the front page, `UploadModal.tsx`, `DocumentDrawer.tsx` the file, details, versions and history, `SpacePicker.tsx`,
  `docUi.tsx`, `lumenDocs.tsx` Lumen's front door, step bar, quick filters and floating selection bar); `components/billing/BillFiling.tsx` and `BillFiledIn.tsx` (where a bill is kept)
- api: `routers/documents_router.py` (`/api/documents/...`), `documents.py` (everything it writes), `documents_explorer.py` (places, browsing,
  moving, where a filed paper is kept)
- sql: `.cursor/db/migrate_documents.sql`
- tables: `orion_ods.document`, `document_version`, `document_blob`, `doc_folder`, `document_activity`, and for the automatic filing
  `document_placement` (`.cursor/db/migrate_documents_filing.sql`, written by `documents_filing.py`). None of them
  is loaded into the warehouse and none has an entity form.

**Rules.**
- **It works like a file explorer** (`documents_explorer.py`, `GET /documents/browse`). A *place* (a node of the address, `?node=`) is the top
  (`root`), `company`, `clients` / `cases` (every one, with or without documents), one client or case, a folder (`folder:12`), `all` or `trash`;
  `home` is the Overview. The tree on the left opens the company, the clients and the cases and the folders inside them (a branch is read
  when opened); the bar above the list shows the way in (each step opens it and takes a drop) with Back, Forward and Up. A place shows its
  own folders and documents, as a computer does: the number beside a folder counts everything inside it, but opening it shows only what is
  directly in it; a search (or a filter) looks through everything inside the place and lists only documents. At Clients and Cases the search
  box finds a client or case by name. Click selects (Ctrl and Shift add), double-click or Enter opens (a tap on a phone), right-click gives a
  menu, F2 renames, Delete deletes, Backspace goes up, and the list can be shown as a list or as icons. A folder is made in the place
  you are in (New folder). A folder that is deleted drops out of the tree on its own (no message is left there); an error the tree does
  show (the top level could not be read) can be dismissed. Documents and folders are **dragged onto a folder, a case, a client or Company documents** (in the list, the tree
  or the bar) or moved with **Move to…**, which opens the same folder chooser used everywhere (`FolderPicker`); files and **whole folders** dragged from the computer onto
  a folder are uploaded into it (see "Uploading a folder"). `POST /documents/move` does it: a document moves to any folder, case, client or the company (its kind is set to
  Other if the new place has no such kind), a folder moves within its own case, client or the company (no deeper than
  `MAX_FOLDER_DEPTH`, never into itself, never a folder Orion keeps), at most 200 at a time. Old addresses (`?view=case&code=...&folder=...`) still open.
- **In Lumen the same module is drawn for finding, adding and opening papers** rather than as a file explorer (nothing it can do changes; the Classic screen is as it was). `/documents` opens a **front door**
  (`lumenDocs.LumenLanding`, standing for both the Overview and the top level): a large search (typing moves to the results and keeps the cursor), Add documents and Add a whole folder, four tiles (Expired,
  Expiring soon, Drafts, All documents) that open the filtered list, the places papers live in in plain words (Company documents, Clients, Cases, Google Drive, every document in one list, Trash),
  what needs a look and what changed lately, and the tags. Inside a place: the way in as step pills (Back, Up, each step takes a drop), a search, **one-tap chips** (Everything, Expiring soon, Expired, Drafts;
  *More filters* has the kind and tag), folders as cards and documents as roomy rows or cards with a status, an expiry, a size and a three-dots menu (the right-click menu). **A click opens** a folder or a
  document; a round tick box on each row selects (Ctrl and Shift still work); the tools for what is ticked (Move to, Copy to Drive, Set status, Delete, Restore) are a bar floating at the foot of the window.
  The folder tree is a **Folder map** button (kept on this device), hidden until asked for. A document opens with its four key facts (when it expires, kind, whom it belongs to, version) above the file. **Add documents**
  starts with the drop area, then where they are kept, then the details (the same fields and rules). Update filing is in the three-dots menu of the page.
- **A document belongs to one place**: the company, one case or one client (`scope`, with `case_code` or `client_code`
  checked by the database). A document can be moved to another place in its edit form; its kind then has to fit the new
  place (`documents.CATEGORIES`). A case or client that has documents cannot be deleted (foreign key).
- **A new file is a new version.** Versions are never changed or removed (until the document is deleted for good).
  "Make current" on an old version adds a new version that shares the old file. A file identical to the current version is
  refused.
- **A file is stored once per distinct content** (`document_blob`, keyed by its SHA-256), so the same file filed twice, or
  restored from an old version, takes no more room. Filing a file that is already on file elsewhere works and tells the
  person where. The files are in the database, so the encrypted daily backup covers them (see `docs/backup.md`).
- **What is accepted is decided on the server** (`documents.check_file`): the extension must be one of `FILE_TYPES` (PDF,
  JPG, PNG, WebP, Word, Excel, PowerPoint, TXT, CSV), the file's first bytes must agree with it, and it must be no
  larger than 300 MB (`documents.MAX_BYTES`; the Drive copies use the same number, `gdrive_client.MAX_FILE_BYTES`). A file over 50 MB is kept but its words are not read for search
  (`documents.EXTRACT_MAX_BYTES`). Only PDF and images are ever shown inline (`employee_documents.is_inline`); everything else is sent
  as a download, with `nosniff`, so an uploaded page of script is never served as a page. The document's panel shows the file beside its details;
  **Full screen** (`ui/FullScreenViewer.tsx`) shows it over the whole window (a PDF in the browser's viewer, a picture fitted or at full size), with New tab and Download, and Esc closes it.
- **Search** looks through `title`, kind, tags, description, file name, document code, case and client name and
  `content_text`, the words taken from the current version when it is uploaded (`documents.extract_text`: `pypdf` for
  PDFs, the XML inside Office files, plain text). A scan has no words and is found by its title and tags only. Every word
  typed must match. Replacing the file replaces `content_text`.
- **Expiry.** `expiry_state` is `expired` (past), `expiring` (within `reminder_days` of today), `valid` or `none`. A
  Superseded or Archived document has `none`: it raises no alert. The list filter (`_where`) and `expiry_state` are two
  writings of the same rule; change both together. The overview and the dot beside a case or client count
  only Draft and Active documents.
- **Confidential** documents are seen only by admins and people who may change documents (`documents.can_see_confidential`).
  For everyone else they are left out of lists, search, counts, the checklist, the file and the detail (it answers 404,
  so their existence is not given away).
- **Deleting moves to the trash** (`is_deleted`); a trashed document cannot be edited, can be restored, and only an
  admin can delete it for good (`/purge`), which removes its versions and history and any file nothing else uses.
- **Folders** belong to a place and can be nested four deep; a name is unique among its siblings (ignoring case). A
  folder can be renamed, and deleted plainly only when it holds no folders and no live documents (`delete_folder`). **Deleting a folder that holds
  things** shows first what would go (`GET /folders/{id}/contents`, `documents.folder_contents`, a read: what the person may not see is neither named nor counted): how many documents, file versions and how much,
  the folders inside, and the titles; the red button then deletes the folder and its folders and moves its documents to the trash
  (`POST /folders/{id}/drop`, `documents.drop_folder`, `DropFolderDialog`), from where they can be restored to the top level of their place.
  The numbers shown go back with the confirmation, and a folder that has changed since (a document added while the warning was open) is not
  emptied: it is looked at again. Never dropped: a folder Orion keeps itself (`system_key`), one that holds papers Orion filed
  (bills, employee and EMD papers: `documents_filing` is their only writer; the dialog says to choose another place for them first) and one
  with confidential documents the person may not see. "Add the usual folders" adds
  `documents.STANDARD_FOLDERS` and can be repeated.
- **Folders can be made while filing** ("New folder" under the Folder box of the upload dialog, inside the chosen folder if
  one is chosen), and **any case or client can be opened from the "Open any case or client" box**, including one with no
  documents yet, which the left list otherwise leaves out (it lists only places that have documents). An opened empty
  place is shown in the list as "No documents yet". Folders are kept with their place in the page's state, so a place
  never shows another's folders, and the upload dialog is built afresh each time it opens.
- **Uploading a folder** (`components/documents/uploadFolders.ts`, `UploadModal.tsx`, `POST /documents/folders/tree` -> `documents.ensure_folder_paths`). A folder
  from the computer is chosen (**Upload folder** on the page, in the right-click menu, or **Choose a folder** in the upload dialog) or dragged onto the page, a
  folder row, or the dialog. It is read all the way down in the browser; its folders are made inside the place (and inside the chosen folder) with the same names, and each
  file is filed in its own folder. A folder that is already there is used, whatever the case of its name, so uploading the same folder again adds to it rather than doubling it
  (a file identical to one already filed is still filed, and the person is told where the same file is). Folders nest at most `MAX_FOLDER_DEPTH` deep: anything deeper is
  kept in the deepest folder that fits, and the person is told. Files of a type Orion does not keep, hidden and temporary files (`.git`, `.DS_Store`, `Thumbs.db`, `~$` files)
  are left out and counted in the dialog; at most 1,000 files and 500 folders are taken at a time. Every file in the folder takes the dialog's status, tags and Confidential
  tick; its kind is guessed from its name and is "Other" when the name says nothing (changed per file in the list). An empty folder is made too when it was dropped
  (the browser does not report one chosen with the button). The folders are made first, then the files one after another, so a bad file does not stop the others and a
  second try finds the folders already there. Not yet: uploading a folder to Google Drive.
- **A case's papers**: the case view shows which of `CASE_CHECKLIST` (tender, work order, contract, guarantee,
  insurance) have a live Draft or Active document, and clicking a missing one starts an upload of that kind.
- **History** (`document_activity`): uploaded, new version, edited, moved, viewed, downloaded, deleted, restored, with who
  and when. Opening a document that a browser can draw counts as viewing it. Nothing in it can be changed through the app.
- **Google Drive** (`gdrive.py`, `gdrive_client.py`, `routers/gdrive_router.py`, `components/documents/DriveSection.tsx`; tables `gdrive_connection`, `drive_link`
  in `migrate_gdrive.sql`). An admin connects the company's Google account once (Documents > Google Drive > Connect). Drive then appears as a place in the
  tree and address bar (`?node=gdrive`, `gdrive:<folder id>`), browsed like Orion's own folders: folders, files, search of all Drive, new folder, upload, rename,
  move, download, move to Drive's trash. Between the two: **Copy to Google Drive…** / **Move to Google Drive…** on documents (menu, selection bar, or drag onto a Drive folder
  in the tree), and **Copy into Orion…** / **Move into Orion…** on Drive files (to any folder, case, client or the company; a Google Doc or Sheet comes as PDF or Excel). A copy is
  remembered (`drive_link`) and shown on each side ("Google Drive" in the document's details). A *move* trashes the original only after the copy exists. A Confidential
  document or an employee's paper is sent only after the person confirms it (`allow_confidential`), and a paper Orion filed by itself is copied, never moved out. Not yet: copying a whole
  folder as one, Shared Drives, two-way sync of a folder, per-person connections.
  - *Bills.* The company setting (Drive settings: never / ask / always, and a folder) and a tick on each new bill ("Also save a copy to Google Drive", with a folder chooser; the bill's
    page has the same for an issued bill) save the bill's PDF to Drive. The file **follows the bill**: an edit, a cancellation (the file is renamed "(cancelled)") or a new text size
    replaces its content (`sync_bill_quietly`); a failure is shown on the bill with **Try again** and never affects the bill. **Stop updating** leaves the file as it is.
  - *Which Drive.* `gdrive_client.configured_mode()`: with `ORION_GOOGLE_CLIENT_ID` and `ORION_GOOGLE_CLIENT_SECRET` in the `.env` it is Google's; without them a development computer
    uses a stand-in Drive in `data/fake-drive` (and says so on screen) and production has none. Switching is only adding the credentials, restarting and pressing Connect (DEPLOYMENT.md,
    "Google Drive"). Only `gdrive_client.py` talks to a Drive; both Drives answer the same `DriveClient`.
  - *Who.* Anyone with Documents access can browse; copying, uploading and changing need permission to change documents; connecting, disconnecting and the settings are admin only.
    (A separate Drive permission flag is not built yet.)
- **Everything Orion makes or collects is filed here by itself** (`documents_filing.py`). A tax invoice that is issued, edited or cancelled, an
  employee's Aadhaar, PAN and other papers, and an EMD's receipts and refund papers each become a document, so the Document Center is the one
  place to find every paper while Billing, the employee and the EMD stay the one place each is changed.
  - *Where they go.* A bill is at home in its **case** (`Billing and payments / Tax invoices / FY 2026-27`) and is also filed in its **client**
    (`Billing / Tax invoices / <site> (CS-0001) / FY 2026-27`); the year is the financial year of the bill date. An EMD's papers are in the
    case under `Tender and bid / EMD and guarantees` and in the client under `Tenders and EMD / <site>`. An employee's papers are in the
    company under `People and HR / Employees / <name> (EMP-0001)` and also under the site the employee works at
    (`Compliance / Staff records / <name>`); they are filed **Confidential**, so only people who may change documents (and admins) see them
    here. A bill with no case (an old one) is at home in its client.
  - *One document, several places.* The document has one **home** (its scope, case or client, and folder) and any number of **placements**
    (`document_placement`): the same document shown in another place and folder, not a copy. Opening it, its versions and its history are one.
    The case's and the client's counts include it, and opening a folder shows what is inside the folders below it.
    "All documents" counts each once.
  - *What is kept.* A bill's file is its PDF as issued (without the letterhead); an edit is a new **version** of the document, a cancelled
    bill is **Archived** and its title says cancelled, and nothing is replaced. An employee's or EMD's file is the one uploaded on the record,
    stored once more here by its content (the same bytes are not stored twice in the Document Center).
  - *It follows its source.* A filed document names its source (`source_type`, `source_ref`, unique, so nothing is filed twice) and
    the state it shows (`source_version`). The folders are made by the filing (`system_key`) and renamed when a case or client is; a folder a
    person made with the same name is taken over, not doubled. When an employee changes site, the placement moves; when a source is
    deleted its document goes to the trash; an empty folder the filing made is removed.
  - *Choosing where it is kept.* A filed paper can be kept in any folder, case, client or the company: when a bill is made ("Keep the bill in
    Documents" on the bill form, with the places it will be in shown first), on the bill's page ("Kept in Documents", each place a link, and
    **Keep it somewhere else**), or by moving the filed document in the Document Center. The choice is stored for the source, not the file
    (`document_filing_choice`, written only by `documents_filing.set_choice`; `PUT /documents/source/{type}/{ref}`; it needs permission to change
    documents), so a new version of the bill goes to the same folder. The chosen folder becomes the document's home and the usual place in
    the *other* space stays as a placement (a bill kept in a client folder is still in its case; one kept in a case folder is still in its
    client). "Back to the usual place" removes the choice. It goes with the folder if the folder is deleted, and with the source. Only the
    place changes: the filed copy of the bill is not drawn again.
  - *Not changed by hand.* A filed document cannot be edited (title, kind, status, dates), deleted or given a new version in the
    Document Center: it says where to change it (it can be moved: that is a choice, above). Its **tags and description** can be changed. A filed folder cannot be renamed. An admin can
    still delete one for good from the trash, and the next filing files it again.
  - *When it runs.* `documents_filing.reconcile` is safe to run at any time and does nothing when nothing changed. It runs after a bill is created,
    edited or cancelled, after an employee or EMD file is uploaded or deleted, after an employee, case, client or EMD is saved or deleted
    (`entity_service`), shortly after the API starts and every six hours (this files everything that existed before the feature), and
    when someone with permission to change documents presses **Update filing** (`POST /documents/filing/update`). A failure while filing is logged and never
    stops the save that caused it. Letters, statements and reminders sent to clients are not filed yet.
- Upload is one file per request (`POST /documents/items`); the browser sends a batch one file after another, so a bad
  file does not stop the others. "Upload" suggests a kind from the file's name (`guessCategory`); it is only a start.

**Depends on.** Sign-in. `documents_access` opens and downloads documents; `documents_write` uploads, edits, moves,
deletes and restores, and sees Confidential ones; `admin` deletes for good. Cases and clients (`orion_ods.case`,
`client`) are what a document is filed under.
**Used by.** Billing (every bill is filed here), employee documents and EMD documents (their files are filed here as well as kept on the
record). Those files stay where they are uploaded and are changed there.

---

## Bank

**Does.** Keeps the firm's one bank account: what it holds today, every movement behind that figure, where the balance
is heading, and whether the book agrees with the bank. It is Utilities > Bank (`/bank`) with four tabs: Overview
(the balance, this month and year, interest and other income, charts, a cash forecast), Ledger (every movement with the
balance after it, filters, CSV export, adding and voiding entries), Reconcile (upload a bank statement, match it to the
book, work through what does not match) and Account (the opening balance, and the history of everything done). The same
figures appear on the Orion dashboards as the **Cash** tab (`/dashboard/orion/cash`, for people with Bank access) and as
a balance strip on the Overview tab, and the Copilot can answer about them.

**Where.**
- ui: `pages/bank/` (`BankPage.tsx` the tab strip and what the tabs share, `bankContext.ts`, `BankOverviewPage.tsx`,
  `BankLedgerPage.tsx`, `BankReconcilePage.tsx`, `BankAccountPage.tsx`), `components/bank/` (`EntryModal.tsx`,
  `StatementUpload.tsx`, `LineQueue.tsx`, `BillText.tsx`, `BankGlance.tsx`), `bank/format.ts` (money and days),
  `pages/dashboards/CashDashboard.tsx`; `bankApi` in `api/client.ts`; the types in `types.ts`
- api: `routers/bank_router.py` (`/api/bank/...`), `bank.py` (everything it does), `bank_statement.py` (reading a statement),
  `bank_match.py` (matching and recognising lines), `dashboard/views_cash.py` (the Cash tab), `ai/tools/bank.py` (the Copilot),
  `ai/features.categorise_bank_lines` (AI help sorting lines)
- sql: `.cursor/db/migrate_bank.sql`
- tables and views: `orion_ods.bank_account`, `bank_entry`, `bank_statement_import`, `bank_statement_line`, `bank_match`, `bank_audit`
  and the views `bank_movement` and `bank_expected`. None is loaded into the warehouse and none has an entity form.

**Rules.**
- **The balance is never stored.** It is the opening balance (typed once on the Account tab) plus every movement from the
  opening date to today (`bank.get_account`, `summary`, and the running balance in `bank.ledger`). Money before the
  opening date is inside the opening balance and is not counted again.
- **Several accounts, and cash.** An account (`bank_account`) is a `bank` account or a `cash` account, each with its own opening balance and date.
  Every money event names the account it touched: a client payment on a bill (`case_transaction.account_id`, "Received into"), a GST payment
  (`bill_gst_payment.account_id`, "Paid from") and a bank entry (`bank_entry.account_id`); the payment forms offer the choice only when there is more than
  one account (the one used last first). A receipt or GST payment recorded before accounts existed has no account and belongs to the **first account**
  (read that way by the view `bank_movement`, so applying the change moved no balance). Expenses count against the first account until they have payments
  of their own (a later step). A balance is per account: `bank._balance` adds, for each account in view, its opening balance and its movements from its own
  opening date; the Bank pages have a switcher (one account, or **All accounts** added together, whose ledger running balance brings each account's opening
  balance in on its opening date). A statement belongs to one **bank** account (a cash account has none: it is counted, not reconciled; the count and
  transfers between accounts are a later step), a statement line can be matched only to money of its own account, and reconciliation is of one account.
  The forecast, the Cash dashboard tab and the Copilot's bank tools show all accounts together.
- **Nothing is entered twice.** The view `orion_ods.bank_movement` reads the firm's money from where Orion already holds
  it: a client's payment (a Committed `case_transaction`, on the day it was received, with its GST), an expense (a Committed
  `expense_transaction`), GST paid on bills (the non-reversed `bill_gst_payment` rows, a payment recorded in one go being
  one movement) and EPFO and ESIC paid on bills (the non-reversed `bill_statutory_payment` rows, the same way). So a payment reversed on a bill, or an expense cancelled, changes the balance by itself, and the Bank
  module never writes those tables. What has no record elsewhere (interest, other income, bank charges, loans, tax paid,
  PF and ESI, salary paid outside Orion, the owner's money, a refund) is a `bank_entry`, made on the Ledger or from a
  statement line.
- **An expense that looks like one already entered is warned about, never refused.** Adding an expense (the form's review step, the Excel upload result,
  the Copilot's confirmation) looks for another that is not cancelled with the same expense type and case and the same amount (with tax and GST, to the
  paisa) on a date within seven days either side (`entities.find_possible_duplicates`, `POST /entities/Expense Transaction/duplicate-check`). The form shows
  the matches with "Save anyway"; an upload saves as before and lists the rows that look like another (an expense already recorded the same day is the
  merge by design, so only other days count). A regular monthly expense of the same amount is weeks apart, so it is not flagged.
- **An expense can be entered as already paid.** On the Expense form (and in the Excel upload) three extra questions are asked when an expense is
  ADDED: **Paid On**, **Paid From** and **Payment Reference** (`create_fields` of the entity; they are not columns of the expense). Fill in Paid On
  and the expense is saved and paid in full in the same transaction (`entity_service.create`, `payables.pay_on_entry`), so the bank moves on that day
  from that account; leave it empty and the expense is owed until a payment is recorded in Bank > Payables. With more than one account, Paid From is
  required; a day before the account opened is allowed (it is already inside the opening balance); only an Incurred expense can be marked paid. The
  questions are offered only to a person who may change the bank, saving takes an `Idempotency-Key` (a second click or a retry pays once), and in an
  Excel file they apply only to new rows (a row about an existing expense with them is refused: record its payments in Payables).
- **Status words on the Expense screens.** The stored statuses are unchanged (`Committed`, `Prospective`, `Cancelled`) but the Expense form shows
  **Incurred (a real cost)**, **Planned (not happened yet)** and **Cancelled** (`option_labels`), and the Excel upload also accepts Incurred and
  Planned (`option_aliases`). Status answers "did the cost happen?"; Unpaid / Part paid / Paid answers "has the money left?". Revenue keeps
  Committed and Prospective.
- **A minimum balance warns, never blocks.** An account can be given an optional **minimum balance** (Bank > Accounts, `bank_account.low_balance_floor`).
  Orion then warns, with a banner on the Overview and an insight in the Copilot (and `get_bank_balance` says so), when an account is below its minimum, and when
  the accounts together are expected to fall below their minimums within two weeks (`bank.alerts()`, from what Orion already knows is coming, with overdue
  money left out). With no minimum set there is nothing to say; a minimum is never enforced.
- **Salary reaches the bank in pay runs** (Bank > **Payroll**, `payroll.py`, the only writer of `orion_ods.salary_run`). Salary lines are entered in
  Operational Data (Employee Transaction). Salary Paid is not typed in: a new line starts as No, and it shows as read-only, set by Payroll. One bank transfer pays many lines, so marking a month paid is a **pay run**: the lines that were
  paid (all of the month's unpaid ones to begin with; a line left out stays owed), the day, the account (named when there are several) and the bank reference.
  It needs the confirmation, the number of lines and total the person saw (`seen_count`, `seen_total`, so two people cannot both pay the same lines) and an
  `Idempotency-Key`; the day is not in the future, and a day before the account opened is allowed (that salary is already inside the opening balance,
  which is how months paid long ago are marked paid). The bank holds **one movement per run** (what its lines came to), so one transfer on a statement
  matches one movement, and the forecast holds each month's unpaid lines at the month end. Reversing a run needs a reason: its lines go back to unpaid, the
  money returns to the account, and the run is kept, marked. A line in a run cannot be changed (employee, month, amount, paid state) or deleted until the
  run is reversed, and a line cannot be marked paid any other way (database trigger `salary_line_follows_its_run`; the form says so), so
  the dashboards' "salary pending" and the bank always agree. Reading months and runs needs Bank access (they are totals); seeing who is in a month's
  unpaid salary, marking it paid and reversing need permission to change the bank. Every line that was marked paid before pay runs was given a run on
  its own date (once), so the flag keeps its meaning. The entry kind `salary` (Salary and wages) stays for salary paid outside the payroll lines; using
  it for salary that is also marked paid in Payroll counts it twice.
- **Expenses are owed until they are paid** (Bank > **Payables**, `payables.py`, the only writer of `orion_ods.expense_payment`). A `Committed`
  expense is a cost taken on; it reaches the bank when a payment is recorded on it. A payment is an amount (no more than is left), the day (not
  in the future, not before the account's opening date), the account it left, and an optional reference; it needs the confirmation, the amount the
  person saw as already paid (`seen_paid`, so two people cannot both settle it) and an `Idempotency-Key`. Reversing one needs a reason and puts the money
  back; the payment is kept, marked reversed. Unpaid / Part paid / Paid is worked out from the payments. The expense has an optional **Pay by** day
  (`due_date`; empty means the transaction date) that drives the ageing (not yet due, 0-30, 31-60, 61-90, over 90 days late) and the forecast, which
  holds what is still unpaid on that day. A paid expense stays Committed and is never worth less than what was paid on it (the trigger
  `expense_keeps_its_payments`; the form says which payments are in the way), and an expense with any payment on record cannot be deleted. Reading
  Payables needs Bank access; recording or reversing needs permission to change the bank. A statement line matches an expense **payment** (the movement's
  `source_ref` is the payment number). When payments began, every Committed expense got one payment for its full amount on its transaction date, so no
  balance moved; an expense entered after that starts unpaid, so a historic expense loaded from Excel as Committed shows as owed until it is marked paid.
- **An entry is never deleted.** A wrong one is voided with a reason (`bank.void_entry`); it stops counting, stays in
  `bank_entry` and in `bank_audit`, and a statement line matched to it goes back to unmatched. An entry's date cannot be in
  the future or before the opening date. Making one takes an `Idempotency-Key` (see Billing), so a double click or a retry
  records it once.
- **Changing the opening balance or its date moves every balance**, so it needs the confirmation screen (which shows the
  balance now and after), is refused without `confirm`, and is audited with the old and new figures. The opening date
  cannot be moved later past a statement line that is already matched.
- **Interest and other income** are the entry kinds `interest` and `other_income` (`bank.INCOME_CATEGORIES`). Loans, refunds
  and the owner's capital are not income. **Money received with no bill** (an advance, a deposit) is the entry kind
  `other_receipt`; it needs a note (who paid, why there is no bill), is not income, and is the only way to put it in the
  balance: the Transaction form, the Excel upload and the Copilot refuse a Committed revenue line with no bill. They show on the Overview, in the Cash tab (a chart, a table of each receipt, a
  figure) and on the Orion Overview strip, and the Copilot reads them (`get_bank_balance`).
- **Reconciliation** matches each statement line to the movement(s) of the book it is. A match needs the same direction
  and exactly the same amount (to the paisa) within a few days (`bank_match`). Orion matches on its own only what is
  unambiguous both ways (the line has one candidate and the candidate has one line, or exactly one candidate carries the bill
  number or reference that is on the line); anything else is offered as a suggestion with the reasons (days apart, the bill
  number, the client's name), and a person clicks. One deposit that pays several bills is found too (two to four
  movements that add up to the line) and is never matched without a click. A movement is on one line at most
  (`UNIQUE (source, source_ref)`). A line can be recorded as a new entry (made and matched in one step), set aside with a
  reason (a transfer between the firm's own accounts, a duplicate) and brought back, and a match can be undone.
  Nothing matched or set aside is deleted.
- **Matched, then changed.** A match is to a movement of the book, and the book can change under it: a payment reversed on its bill, an expense
  cancelled, a GST payment taken back, an amount edited. `bank.exceptions` finds every `bank_match` whose movement has left the view `bank_movement` or
  whose amount no longer equals the matched amount, and says why in plain words (`_why_it_broke`). Such a line is shown on Reconcile under "Matched, then
  changed in the book", counted in the Overview's "Not yet reconciled" and the Cash tab's figure, and makes the reconciliation state "does not add up"
  until a person returns it to unmatched (`clear_exception`, which writes `match.exception_cleared` with what broke to the history and matches again
  whatever is certain, so a payment reversed and recorded afresh matches its line on its own). A line that is not broken cannot be "cleared".
- **Does the book agree with the bank?** (`bank.reconciliation`) The balance on the latest statement line against the
  book's balance that day. The difference is explained by the movements the bank does not show (not matched) and the
  statement lines the book does not hold (not matched, not before the opening date, set aside included); what is left,
  `unexplained`, is zero when the opening balance is right and no stretch of the statement is missing. The states are
  `reconciled` (nothing loose), `explained` (loose items explain the difference) and `unexplained`.
- **Statements** are CSV or Excel files (`bank_statement.py`; a PDF or the old `.xls` is refused, with what to do instead),
  up to 6 MB and 20,000 lines. The header row is found by the names banks use; a person can correct any column and
  the file is read again. Dates, Indian digit grouping, `Dr`/`Cr`, separate debit and credit columns or one signed amount,
  a newest-first file and a narration wrapped over two rows are understood. When the file has a balance column Orion checks
  that every line's balance follows from the one before (a break means a column was read wrongly, and is shown before
  anything is saved). The file is read again on the server when it is imported; nothing the browser says about its contents
  is trusted. The file itself is not kept: its lines are, each with a fingerprint (`bank_statement_line.fingerprint`, unique
  per account), so uploading the same period twice, or two uploads that overlap, never holds a line twice, and the same
  file (its SHA-256) is refused. Lines dated before the opening date are set aside automatically. A wrong upload can be taken
  back (`bank.remove_import`) unless some of its lines are matched.
- **AI help** is only for sorting lines Orion's own rules (`bank_match.RULES`: interest, charges, tax, GST, PF/ESI, salary,
  loans, refunds) cannot name, and only through `ai/assist.py` like every other AI help: local model first, a cloud
  model only when the policy allows and the person says yes for that one request. Account and card numbers in
  narrations are cut to their last four digits first (`bank_match.mask_numbers`). It only suggests a category and who
  the money was from or to; the person records the line. A category the model invents, or a line it was not asked
  about, is dropped.
- **The forecast** (`bank.forecast`) uses the view `bank_expected`: Prospective revenue and expense entries on the day they
  are expected, and the GST still to pay on issued bills, estimated for the 20th of the month after the bill. Anything
  due before today is shown as overdue and left out of the projection unless the person ticks "count overdue money".
  It is only what Orion already knows; the page says so.
- **The ledger export** (`/api/bank/ledger.csv`) is the ledger with the filters on, oldest first. A cell that starts with
  `=`, `+`, `-` or `@` gets a leading `'`, so a typed note cannot run as a formula in a spreadsheet.
- **History** (`bank_audit`) records the account's creation and changes, entries and voids, uploads and their removal, matches
  (automatic and by hand), unmatches and set-asides, with who and when. Nothing in it can be changed through the app.

**Depends on.** Sign-in. Its own pair of flags: `bank_access` opens the Bank pages, the Cash tab and the Copilot's bank tools;
`bank_write` sets the opening balance, adds and voids entries, uploads and matches statements. Money is the most sensitive
thing in the application, so the flags default to admins only: the first start with this release gives admins both and
nobody else, and each person's access is then set in Admin. Billing (`bill_gst_payment`, `case_transaction` with a
`bill_code`, the bill numbers shown through `BillNumber`), Expenses (`expense_transaction`), and the dashboards (the Cash tab
is built by `dashboard/views_cash.py` from `bank.py`, not from the warehouse, so it is current to the minute).
**Used by.** The Orion dashboards (the Cash tab and the Overview strip; the tab is hidden and refused for people without Bank
access, in the router and in the Copilot's dashboard tools), the Copilot (`get_bank_balance`, `get_bank_forecast`,
`search_bank_ledger`, all read-only: the bank is changed only on its own pages).

---

## Attendance

**Does.** Records who worked at a case in a month, and enters the pay that follows. A **register** is one case and one month with a line for each
person: the days present, the pay for a day, an extra, a deduction and the amount to be paid. Opening a new register lists the case's employees (active, and
employed during the month) with their day's pay worked from their monthly salary; a person is counted or left out with a tick, and the days, the rate, the extra, the
deduction and the amount can each be changed. People who are **not employees** (casual labour) can be added by name; they are saved for the next register and never
become employees. Posting the register enters the pay; paying it stays in Bank. It is Utilities > Attendance (`/attendance`).

**Where.**
- ui: `pages/attendance/AttendancePage.tsx` (the registers, and the People tab), `AttendanceSheetPage.tsx` (one register), `components/attendance/AttendanceModals.tsx`
  (add people, post, reopen, a saved person), `attendance/attendanceCalc.ts` and `attendanceDraft.ts`; the case choosers in `components/bank/PayrollModals.tsx`
  and `pages/bank/BankPayablesPage.tsx`
  and `components/attendance/lumenAttendance.tsx` (Lumen's forms)
- api: `routers/attendance_router.py` (`/api/attendance/...`), `attendance.py` (everything it does)
- sql: `.cursor/db/migrate_attendance.sql`
- tables: `orion_ods.attendance_sheet`, `attendance_line`, `attendance_worker`, `attendance_event`; and on the tables it enters pay in, `employee_transaction.case_code`,
  `employee_transaction.attendance_line_id`, `expense_transaction.attendance_line_id`. The attendance tables are not loaded into the warehouse; the salary lines and expenses are.

**Rules.**
- **In Lumen** the same registers are drawn for filling a month in on a phone or a desk (Classic is unchanged; the figures, rules, Excel and posting are the same code). The list opens on four tiles
  (registers, still drafts, posted, what they come to) and groups the registers under their month, one card each (month, case, who is on it, status, amount); the People tab is cards. A register shows its totals
  first, then **a card for each person**: a round tick to count or leave out, the amount in large figures (it can still be typed over), the days with **- and +** buttons, a bar of the month and a
  "Full month" shortcut, the pay for a day, an extra, a deduction and a note. **Save draft and Post** are in a bar floating at the foot of the window (above the tab bar on a phone) with the running total.
- **One register for a case and a month** (a second is refused, and the case's page opens the one that exists). A register is **Draft** (changed freely, nothing entered) or
  **Posted** (the pay is entered; it is not changed). The people on it are an employee or a saved person, once each; the number of days cannot be more than the month has.
- **A line comes to** days x pay for a day + extra - deduction, never below nothing (`attendance.calculated_amount`; the screen's live figure is
  `attendanceCalc.ts`; both are checked against `backend/tests/attendance_vectors.json`). The amount is worked out until a person types one; a typed amount that differs is marked,
  with a link back to the worked-out one. An employee's day's pay is the monthly salary over the days of that month, so a full month pays exactly the salary.
- **Posting** (`attendance.post_sheet`) needs the confirmation, the number of people to be paid and the total the person saw (a register changed meanwhile is refused), and an
  `Idempotency-Key`. For each person with an amount: an **employee** becomes a **salary line** (`employee_transaction`: the employee, the month, the days, the amount, not paid,
  **the case it was worked at**), and anyone else becomes an **expense** (`expense_transaction`: Committed, the expense type chosen on the register, the case, a description
  naming the register, the person and the days). They are dated the last day of the month, or today for the month in progress; a month that has not started cannot be posted.
  The register needs an expense type when it has people who are not employees.
- **Paying is unchanged.** Salary is paid in Bank > Payroll as a pay run, expenses in Bank > Payables. Payroll's pay screen has a **Case** chooser (the case on the line, else the employee's own):
  choosing a case ticks only its lines, so a month is paid one case at a time or all together. Payables has a case filter too.
- **Reopening** a posted register (with a reason) takes back what it entered, so it can be changed and posted again. It is refused once **any** of it has been paid: a salary line
  in a pay run, or an expense that has had a payment recorded, even one since reversed. The entries it made are locked in the generic forms (`entities.locked_reason`) while it stands, and what
  is taken back is written to `record_deleted`. Every step (made, saved, posted, reopened) is kept in `attendance_event` and shown as the register's History.
- **A person may be warned, not stopped:** an employee who already has pay for the month somewhere else, or is on another register for it, is flagged on the line.
- **Excel**: "Template" downloads a workbook with the case's people listed; "Upload Excel" reads a filled one into the register (nothing is saved until the register is): a row is matched by
  employee code, then by name among the case's people and the saved people, then among all active employees, and a name that matches nobody is a new person. Rows that cannot be read
  are listed with the reason. "Excel" on a register downloads it. "Copy last month" brings the last register's days and rates; "Full month for everyone counted" and "Clear days" fill the days.
- **Saved people** (`attendance_worker`, code `WRK-0001`): name, phone, work, pay for a day, the case they usually work at, Active or Inactive. The same name and phone is not saved twice. They are
  listed on the People tab and offered on registers; an inactive one is not offered on new registers.
- **Warehouse**: a salary line carries `case_code`, and the warehouse puts it at that case (`dw_sync._pit_employee_txn`), so the dashboards show pay at the site it was worked at, not only
  the employee's own case.
- Attendance is its own area: `attendance_access` sees the registers, `attendance_write` makes, changes, posts and reopens them and saves people. A person with it sees the names and the day's pay of the
  employees at a case (not their salaries, Aadhaar or PAN). Not yet: a day-by-day grid, overtime rules, and attaching the signed register (a scan can be filed in the Document Center).

**Depends on.** Sign-in. Cases, employees, expense types. Bank > Payroll and Payables for paying.
**Used by.** The Orion warehouse and dashboards (the salary lines and expenses it enters).

---

## Tenders (GeM and MP Tenders)

**Does.** Finds bids on GeM (the Government e-Marketplace) that the firm could bid for. A person saves searches: tender types
(words in the bid's GeM category, such as "Security" or "Manpower outsourcing"), cities (where the work is), the kind of bid
(services, products or all) and a range of estimated value in lakhs. Orion checks every active search on GeM by itself every
`ORION_TENDERS_CHECK_HOURS` (default 6, 0 turns the schedule off) and when someone presses **Check GeM now**, reads the public
bid document of each bid that fits, and lists what it found with its value, EMD, closing date, contract period, the turnover
and experience asked for, and where the work is. A person shortlists or dismisses each bid. It is Utilities > Tenders
(`/tenders`).

**Choosing the types and cities of a search.** Both are multi-selects (`components/ui/MultiSelect.tsx`): a search box over the list, a tick for each row, chips for what is
chosen, and a word that is not in the list can be typed and added. Cities are chosen from a state's list: **"All N cities of <state>"** takes every one in a click, and
cities of several states can be combined (what is chosen stays when the state is changed). A search may name up to 20 tender types and **100 cities** (`tenders.MAX_TERMS`,
`MAX_CITIES`), which fits every district of the largest state. Each city is a separate question to the portal, a few seconds apart, so the form says a check of
a search with many cities takes several minutes.

**Where.**
- **Two separate tools.** Utilities has **GeM tenders** (`/tenders/gem`) and **MP tenders** (`/tenders/mp`). A search belongs to
  one portal (`tender_search.portal`) and is shown, checked and counted only there; each portal has its own checks
  (`tender_run.portal`), lock, status, "Check now" and System-page entry, and the two may run at the same time. The kinds of
  bid are the portal's own: GeM Services / Products / All, MP Services / Goods / Works / All.
- **Filters** narrow what a search has found, on the page (the list holds up to 5,000): words (title, number, department,
  place), place (the districts found), closing within 3, 7, 15 or 30 days, value range in lakhs, only those stating a value,
  EMD up to an amount; on GeM whether an EMD or a performance guarantee is required; on MP the Tender Category, the tender fee up to
  an amount, or none. Sorted by closing, value either way, or when found. "Clear filters" keeps the sort.
- ui: `pages/tenders/lumenTenders.tsx` (Lumen's closing tile and term chips), `pages/tenders/TendersPage.tsx` (`GemTendersPage`, `MpTendersPage`), `pages/tenders/BidFilters.tsx` (searches on the left, the bids of the chosen one on the right, New / Shortlisted /
  Dismissed / All), `pages/tenders/SearchForm.tsx` (add and change a search; city suggestions come from `/api/location`)
- api: `routers/tenders_router.py` (`/api/tenders/...`), `tenders.py` (searches, the check, matching, the schedule),
  `gem_client.py` (the only code that talks to GeM), `mptenders_client.py` (the only code that talks to MP Tenders)
- sql: `.cursor/db/migrate_tenders.sql`
- tables: `orion_ods.tender_search`, `tender_bid`, `tender_match`, `tender_run`, `tender_question_bid`, `tender_question`. None is loaded into the warehouse.

**In Lumen** the page is built around the deadline (Classic is unchanged; nothing is read or sent differently). It opens on four tiles (new bids across the searches, shortlisted, bids in the list closing within
3 days, when it was last checked); the searches are a row of cards across the top (with their new count and "New search"); a search's long lists of types and cities fold behind "+N more"; the filters are
one line (words, closing within any time / 3 days / a week / a month, the order) with **More filters** for the rest; and each bid is a card led by a **days-left tile** (red within 3 days, amber within
a week, closed or undated in grey), with its number and portal, title, buyer, place, the "To apply" facts as chips, the estimated value in large figures, and Apply, Shortlist, Dismiss.

**Rules.**
- **Only public pages are read**, and nothing is sent to GeM but a search: the "All Bids" listing
  (`bidplus.gem.gov.in/all-bids`, the same request its own page makes, with its form token) and each bid's document
  (`/showbidDocument/<id>`). Nobody's GeM account is used. This is not an API GeM publishes: when an answer is not what the
  code expects, the check stops with the reason in words (`GemError`), on the Tenders page and on the System page.
- **Slowly**: every request waits `ORION_TENDERS_REQUEST_GAP_SECONDS` (default 2, at least 1) after the one before. A check
  reads at most `MAX_DOCUMENTS` (300) documents, those closing soonest first; the rest wait for the next check, and the page
  says so. A network blip (a timeout, a dropped connection) is tried again after 15 and then 45 seconds (`gem_client.RETRY_PAUSES`);
  if the portal still sends nothing the check stops and says so ("connected but sent nothing back in time; its site may be down
  or busy"), and the next check tries again. An answer, even a refusal, is never retried.
- **How far back**: each question follows GeM's list (newest first) back to the bids published `ORION_TENDERS_LOOKBACK_DAYS`
  ago (default 90, between 7 and 365) that are still open, or to its end. `MAX_PAGES` (300 pages, 3,000 bids) is only a
  safety stop; a pass it cuts short is followed again by the next check. A captcha or a refusal (HTTP 403 or 429) stops the check at once: it is never answered
  or worked around.
- **How a bid is found.** GeM is asked for ongoing bids, newest first: by each city when the search names cities (GeM finds
  the city in the bid's consignee address, and a city's list is short), otherwise by each tender type. Of what comes back,
  only bids whose category contains one of the tender types (at the start of a word, ignoring case) are kept. The same
  question asked by two searches is asked once. GeM answers a search that finds nothing with HTTP 404; that is an empty
  answer, not an error.
- **Later checks are short.** Every bid a question returns is remembered (`tender_question_bid`), and how far back its list
  was last followed to the end (`tender_question.complete_from`). A question followed all the way back before stops at the
  first page holding nothing it returned already (GeM lists newest first), so only the first check of a city or type pages
  deep. A search is decided on every open bid its questions ever returned, so a new or changed search sharing a
  question still sees the older bids.
- **Bids appear one by one.** Each search is checked in turn, and within it each city or tender type: bids whose documents
  were read before are recorded at once, and every other bid as soon as its document has been read (a bid matched on GeM's
  word whose document then puts the work elsewhere is taken off its New list). The page marks bids the latest check found
  "Just found", shows them 30 at a time, heads the list with the chosen search's name and terms, and marks the search being
  checked. A running check writes what it is doing to `tender_run.progress` and `current_search_id`
  ("Asking GeM about Bhopal, page 12", "Reading bid documents ... 3 of 20") with its counts every few seconds; the page shows
  it and refreshes the bids when new ones are found. A search deleted or changed during the check is not recorded (its row
  is locked while its bids are written).
- **Where the work is** comes from the bid document's consignee table: the district of each consignee's PIN code (India
  Post's data, `bharatpin`, as Orion's city list uses), else the city's name in that table. A bid GeM returned for a city whose
  document puts the work elsewhere is left out. When the document could not be read, the city GeM matched is used and the bid
  is marked "not confirmed". A failed document is tried again after a day.
- **Value.** Many GeM bids state only the EMD, not an estimated value. A bid with no value is kept only if the search says
  "Include bids that do not state a value" (the default); a search with no range keeps them anyway.
- **Applying.** Each bid has a copy button beside its number and **Apply on GeM**, which copies the number and opens GeM's seller
  sign-in (`gem_client.SELLER_SIGN_IN_URL`) in a new tab; the seller then opens Bids > Participate in Bids and pastes the number.
  GeM publishes no link that opens one bid's application, so Orion does not guess one. In the Orion PROD window the link opens
  the computer's browser, where a GeM sign-in is kept.
- **What applying costs** is read from the document's EMD and ePBG sections (`gem_client.security_fields`): the EMD amount or
  "No EMD", and the performance guarantee's percentage and months or "No performance guarantee". There is never a tender fee:
  GeM's bid document lists "asking for any Tender fee / Bid Participation fee" among the clauses a buyer may not add. A bid read
  before Orion read these (`reader_version` below `gem_client.READER_VERSION`) is read again at the next checks.
- **Statuses.** A newly found bid is New. Shortlisted, Dismissed and back to New are a person's choice and are never changed
  by a check. Changing a search clears its New bids (they are found again under the new terms at the next check);
  Shortlisted and Dismissed stay. Deleting a search deletes its statuses. Bids that closed more than 30 days ago are removed
  unless shortlisted.
- **One check at a time** (a lock in the API process); a second is refused with 409. A check left "running" by a stopped
  server is closed as failed at the next start. Network waits never hold a database connection.
- **Certificates** are checked against Windows' own store (`ssl.create_default_context()`), as a browser on this PC does: the
  bundle httpx carries does not accept the chain that reaches GeM from the office.

- **MP Tenders** (`mptenders.gov.in`, Madhya Pradesh's e-procurement portal on NIC's GePNIC) is the second portal. `mptenders_client.py` reads only pages that ask for no captcha: "Tenders by Organisation", each
  organisation's list (all its active tenders on one page, so a full sweep is about 95 requests) and each tender's details. The
  portal's own search asks for a captcha and is never used. Tenders published within the lookback whose title has one of a
  search's tender types have their details read (closing soonest first): title, work description, product category, Tender
  Category (Goods / Works / Services: a search's kind says which, "All" any), value, tender fee
  (and the total with charges, and whether exemption is allowed), EMD (and exemption), period of work, location and PIN code
  (its district places the work). A search on MP Tenders needs a tender type. An MP tender's bid_id comes from
  `tender_bid_local_seq` (far above GeM's ids) and its `source_ref` is its Tender ID.
- **MP Tenders' links belong to the visit that made them** ("session=T"; another browser gets "Stale Session"), so a check
  follows them within one visit, opening it again if it expires, and the page links to the portal's front page: the Tender
  ID is copied and the person finds the tender there (the portal's search asks them for a captcha). Applying needs the
  bidder's DSC sign-in on the portal.

**Depends on.** Sign-in. `tenders_access` sees the searches and bids; `tenders_write` adds, changes and deletes searches,
checks GeM now, and shortlists or dismisses. Both start on for admins and editors. The internet, and GeM's page staying as
it is.
**Used by.** The System page ("The GeM tender check failed ..." under Needs attention while a search is active).

---

## History of a record

**Does.** Shows who created, changed or deleted a record and what each change was (field, old value, new value), newest
first. Opened from a row of the records table, or the History button next to "Select record" when changing a record.
Anyone with ODS access can read it.

**Where.**
- ui: `components/data/RecordHistoryModal.tsx`, `pages/OperationalDataPage.tsx`, rows in `components/ui/DataTable.tsx`
- api: `routers/entities_router.py` (`GET /entities/{name}/records/{id}/history`), `record_history.py`
- tables: reads `orion_dw.dim_*` / `fact_*`, `orion_ods.record_deleted`, `orion_ods.app_user`

**Rules.**
- History is read from the warehouse, so it is as current as the last load. A record saved since then is flagged
  "not listed yet". A record changed more than once between two loads shows only the final change.
- Only fields on the record's form are compared. A version that changed something not on the form is listed with no
  fields.
- A row saved before the audit columns existed shows no name. A user who has since been removed shows as "A former
  user". Edits made directly in the database, outside the app, have no name.
- Bills are not part of this: they keep their own versions (see Billing).

---

## Profit and loss and the Operating margin

**Does.** Profitability opens with a **profit and loss** for the period and selection in view: Revenue, then **direct cost** (payroll at cases, EPFO and ESIC paid on the bills of cases,
running costs at cases, penalties and short payments held back by clients), giving the **Contribution margin**; then **head office** (payroll, EPFO and ESIC paid on bills with no case, and costs
with no case), giving **Operating profit**. For someone with **Bank access**, and only when the selection is a period (not one client, case or business line), it goes on: bank charges,
interest and other income, **Profit before tax**, and income tax or TDS paid as a memo (cash paid is not the tax expense, so it is not deducted). Depreciation is not tracked and the
statement says so.

**The headline figure is called Operating margin** (it was "Contribution margin"): revenue less all payroll and all expenses, head office included. The margin of one case, domain or
client is a contribution margin, before head-office cost. Operating profit in the statement and the Operating margin on the tab are one number (`test_profit_and_loss.py`).

**EPFO and ESIC paid are a cost, independent of salary.** The cost is the payment recorded on the bill (above), on the day it was paid, against that bill's case (head office when the bill has none). Payroll is a
separate line and neither depends on the other, so a case with no attendance entered still shows its EPFO and ESIC cost. It is counted when paid, not with the wages.

**Where.** `dashboard/pnl.py` (the statement; `build_view(..., bank_access=)` is what lets the bank lines in, read through `bank.entry_totals`), the view `orion_dw.expense_cost` in `dw_schema.sql` (the cost every expense and margin
figure reads), `components/dashboard/ProfitLoss.tsx`. **Not done:** depreciation; income tax as an expense; the employee's own share of PF/ESI (what you record against a bill is counted whole); the EPFO/ESIC cost is by payment day, not the month of the wages;
interest on a loan (a loan repayment is one bank entry and is not split into interest and principal).

---

## Orion dashboards

**Does.** Eight tabs over the Orion warehouse, written for someone running the business rather than entering its
records: **Overview** (revenue, cost, margin, cash and what is owed), **Revenue** (billing by service line, client,
state; concentration; contracts billing below what they expect), **Collections** (cash against billing, ageing of what
is owed, who owes and who is slow), **Profitability** (the **profit and loss**, then margin by case, domain, capability, client type and year; the
case portfolio; cost mix), **People** (headcount, joiners and leavers, attrition, payroll, span of control),
**Pipeline** (tenders by stage, win rate by year, why tenders are lost, what the wins now bill, and the EMD still to come
back), **Fleet** (distance, cost, cars, drivers, km allowance) and **Controls** (cancelled and edited bills, GST and salary
not marked paid, cases not billed, clients with nobody to call and follow-ups due). Every chart, slice and row is a filter; a toolbar sets the period, financial year, client, case, domain,
capability, state, client type and priority. Each key figure shows its change against the earlier period and last
year, a trend, and what it means and how it is worked out. A strip of findings the server worked out sits under the
figures ("What stands out"), each able to filter the page. Every chart can open the **rows behind it** in a drawer
(sortable, searchable, exportable), and there is an "Explore records" menu for the same sets.

**Drilling into a tile.** Click any key figure (the tile says "Explore" on hover) and a drawer opens with that figure taken
apart: by financial year, then by month for the year you pick, then by every dimension that applies (business domain,
capability, state, client type, priority, client, case, and the ones only some figures have, such as expense type,
designation, car model or pipeline stage). Every bar is a filter inside the drawer: pick a year and the month chart, the
other charts and the table of raw rows all narrow to it; pick a bar again to undo. "Show on the dashboard" carries the picks
back to the page. The Tally dashboard works the same way for its billing tiles; its books tiles (debtors, loans, cash...)
open by account group and ledger instead of by year.

**Where.**
- ui: `pages/dashboards/DashboardShell.tsx` (header, filter bar, brief, figures, records drawer) and one page per tab,
  `dashboards/registry.ts` (the tabs and their figures), `dashboards/useDashboard.ts`, `dashboards/kpiIcons.tsx`,
  `components/dashboard/*` (the shell pieces shared with Tally: `DashboardHeader`, `FilterDock`, `DashboardBrief`, `KpiBoard`,
  `MetricCard`, `Section`, `ChartCard`, `Fold`, `States`; and `MeasureExplorer` (the tile drill-down), `RecordTable`, `RecordsDrawer`, `Heatmap`,
  `PortfolioScatter`, `Bridge`, `ReportTable`, ...). In Lumen the brief is a headline (the lead finding on the accent gradient, the others as pills, then "What changed" and "What to do next" columns), and a tab with many charts shows the first few and a "Show N more charts and tables" bar (`Fold`, wrapped around the grid's cards in each tab; the plain look shows all of them). The Orion Overview tab keeps its two stories (Performance, Cash) on show and folds "Where it comes from" and the year-by-year scorecard behind "Show where it comes from…". The Tally dashboards share the same brief, figures and tabs; when nothing has ever been loaded from Tally they say so and link to Tally data, instead of "no documents match these filters".
- api: `routers/dashboard_router.py` (`GET /api/dashboard/{view}`, `/api/dashboard/records`, `/records/{set}`),
  `dashboard/__init__.py` (`build_view`), `dashboard/explore.py` (the tile drill-downs, `GET /api/dashboard/explore/{figure}`),
  `engine.py` (measures, comparison windows, KPI cards), `views.py` and
  `views_ops.py` (one builder per tab), `blocks.py`, `filters.py` (the filter engine and scopes), `insights.py`
  (pure, tested), `kpi_help.py`, `records.py` (drill-through), `windows.py` (period windows, shared with Tally)
- tables: reads `orion_dw` only. No tables of its own.

**How it works.** `GET /api/dashboard/{view}` with the filters in the query string returns one payload: `kpis`,
`series` (by month), `categories`, `tables`, `insights`, `active_filters`, `meta`. A page reads blocks by id, for
example `series('trend')` or `table('domains')`. `meta` carries the comparison labels and the filter options.

**Rules.**
- **Reads the warehouse, not the operational store.** Every scope keeps only the live version of each row
  (`is_current` and not `is_expired`). Case-linked facts are joined to the case, client, capability and domain by the
  surrogate keys they carry, so a client's state, type and priority are those of the day the bill was raised.
  Rosters (employees, cases, cars, opportunities) are read as they stand now. Figures are as fresh as the last
  warehouse load, which the page says.
- **Revenue** is the taxable value of issued bills **less what approved credit notes took off them**, by the month the service was for; **Billed** and **GST on bills**
  are net of credit notes the same way (`fact_bill.credited_*`), and **Owed** is the bill less credit notes less what settled it. **Cash** is the payments
  recorded against bills (`Committed` entries), by the day received, **less what the client held back** (TDS and the like: `fact_case_transaction.deducted_amount`, kept on the entry by a trigger
  on the deductions), because that never reached the bank. **TDS held back** is that part. A bill paid net of TDS is settled: the **collection rate**, the bill's Paid status and Owed
  count cash plus what was held back, and a bill that is settled only with a credit note reads **Settled**. **Input tax credit** is the GST on Incurred costs that carry the supplier's GSTIN and
  invoice number (the same rule as Utility > GST) and **Net GST to pay** is the GST on bills less it; both follow the segment filters, so a client or case filter narrows them to its own costs. GST on a cost with no supplier details is not credit
  (the figure's hint says how much). New figures: Credit notes and Net GST (Revenue and Controls tabs), TDS held back (Collections), Input tax credit (Controls); they are also in the tile drill-down. **Cost** is payroll plus operating expenses before
  GST. **Margin** is revenue less cost on the dimensions all three share; the margin of one case or domain is before
  head-office cost, and a "Head office and unallocated" row carries the rest so rows add up to the total. **Owed** is a
  snapshot (bill total less payments), counted from the bill date; it follows the segment filters but not the period.
- A filter a fact does not carry is ignored for that fact rather than emptying it. A chart leaves out the dimension it
  plots itself, which keeps a click reversible. Ratios of two facts (collection rate, margin, days outstanding) use only
  the dimensions both carry.
- Comparisons exist only where the data covers the earlier window; a part-month or part-year is compared with the
  same days or months before. The finding thresholds (concentration 25%, overdue 25%, 60 days outstanding, attrition
  25%, stale tender 90 days) are named in `insights.py` and quoted in the text of the finding.
- **A drill-down is built from the same scopes and filters as the tile**, so its total equals the tile. A figure is one or more
  parts (an aggregate over one fact) and a rule that combines them; a ratio such as margin % or collection rate is worked out
  for each bar from that bar's own parts, never by averaging ratios. Figures that add up show each bar's share; ratios and
  averages say that their bars do not add up. A figure that is a position today (owed, headcount, active cases) ignores the
  period until a year is picked, and then means the bills of that year.
- **How a dashboard page reads, top to bottom** (the same on Orion and Tally). A header: the title in one line, how fresh the
  figures are (a chip; the detail is in its pop-over), and the few actions (ask the Copilot, open the rows behind the figures,
  copy a link to this exact view). The tabs. One **filter bar**: the common periods (3M, 6M, 12M, This FY, All) are always on
  screen, beside a box for exact dates and a financial-year picker; every other filter sits in a group named for what it is
  about (Orion: **Client** holds client, client type, priority and state; **Work** holds case, domain and capability. Tally:
  Company, Client, Documents), each one button that names what is selected. Clicks on charts show underneath as removable
  chips, and a thin bar runs while figures are recalculated. Then the **brief**: *What matters* (the server's findings,
  flagged ones first, then notes, then good news; "Nothing is flagged" is said outright when that is so), *What changed*
  (the figures that moved most against the comparison window, each opening its drill-down), and *What to do next* (one step
  per finding: open the tab that explains it, narrow the page to it, or ask the Copilot why). Findings beyond the first three
  wait behind "Show more findings". Then the **figures**: the first few on each tab (the order in `dashboards/registry.ts`)
  are headline cards with a trend; the rest are quiet rows in one panel. Then the charts, in titled sections; heavy detail
  (the financial-year scorecard) is collapsed until opened. Each chart says in a line what it shows and keeps its long
  explanation behind the (i); moving over a month lifts it and says how it moved against the month before, and a legend
  entry hides or shows its series. The Tally dashboard has the same "Ask AI" button and brief steps as Orion's;
  the Copilot reads both (see the Copilot section).
- **The period and the financial year are one choice.** Picking a period (a preset or two dates) clears the financial
  year, and picking a financial year clears the period and any clicked month. The filters live in the address
  (`useDashboardFilters`), and changes made in the same click are applied one after another, each on the last, so the
  second never undoes the first.
- **A dashboard opens on the financial year we are in** (Orion and Tally alike). With no period in the address the screen asks
  for `fy=current` (`requestFilters` in `useDashboard.ts`) and the server turns that into the year (`windows.resolve_fy`: the
  year the later of today and the newest data falls in, never past today, so in early April, before the new year has bills, the
  year just ended is shown) and says which in its answer. "All" and "All years" are chosen by name (`fy=all` in the address), so
  they are still one click away; "This FY" and Reset return to the default. The API itself, and the Copilot's tools, still read
  an unset period as all time: only the screens ask for the current year, and tell the Copilot's page context the same.
- **A year in progress is set against the year before in two ways** (`windows.comparison_windows`, `engine.full_change`, the
  `compare()` in `tally_dashboard.py`). Every period figure carries its change against **the same stretch of the year before**
  (1 April up to the same day) and against **the whole of it**; the key figures have a *Compare with: Same period | Full year*
  switch (kept in this browser) that chooses which leads, and the other stays beside it on a headline card and in the pop-over of
  a supporting figure (`withCompare` in `dashboards/compare.ts`). If the chosen one cannot be worked out for a figure (the year
  before had none of it) the chosen one still leads, with its own label and dates, and says there is no percentage to show
  (the other stays beside it); a comparison is never shown under the other one's name. Figures that are not one of the plain
  totals are worked out for each comparison window the same way: attrition, days to decide, cars on the road and km per day
  (`Dash.period_kpi(at=...)`), and Tally's percentages (GST %, credit note rate, top client) and income lines (`share_kpi`,
  `window_totals`). The switch appears only for a financial year, since a
  month or a date range already has its own previous period and same period last year; a finished year has one comparison, since
  the two are the same. A balance as at today is not compared. **Switching it must not move the page or change a height**: a card
  keeps the room for its second line, the brief keeps the height of two rows of changes (`DashboardBrief`), and the tab strip scrolls
  only itself, never the page (`ViewTabs`; it once called `scrollIntoView` from a ref on every render, which threw the reader back to
  the tabs whenever anything re-rendered). Check any new element on a card against that: toggle the switch and watch the scroll.
- **Tooltips are readable in every theme.** A chart's colours are mid-tones that work as shapes on either surface, but as text on a
  white card amber, lime or sky are nearly invisible (the chart library's default tooltip painted every line in its series colour).
  Every chart tooltip is drawn by `ChartTooltip.TipCard`: a title, one row per figure with the colour only as a small swatch, the
  words and numbers in the theme's own text colours (checked against the surface by `check:themes`), and an optional note; a
  donut slice also says its share. Hover cards (`HoverCard`, the (i) and the comparisons) use `.tip-surface`, a solid surface,
  because through the old 94% one the figures behind showed. The donut's tooltip sits above the total in its hole, and the value
  at the end of a bar is one line of text, not wrapped. Do not give a chart a bare `<Tooltip>`; `test_tooltips.py` fails if you do.
- **A tooltip is about what the pointer is on.** In a chart of several series (revenue by month and capability, an assistant chart) the
  tooltip is shared by the month, so each bar, area and line is bound with `useSeriesFocus().bind(key)` and the tooltip is built
  by `SeriesTip`: the hovered row is lifted and the note names that series, how it moved against the month before (`format.movement`:
  % for money and counts, points for a percentage) and, where the rows add up to a total, its share of it. In the month under the
  pointer the other segments of the stack dim a little. Between segments, or on a lone series, it is about the first series. A KPI's
  sparkline says the same for the month under the pointer. A new multi-series chart binds its series the same way.
- **A chart never gets its height from itself.** `CategoryBar` sizes itself to 100% of its box (`Fill`); if the chart were also what
  gives the box its height, the measurement and the height would chase each other. On a whole-pixel screen that settles, which is
  why it passed every check; with display scaling (125%, 150%: most office laptops) the sizes are fractional and it never does. It
  showed as every chart in a KPI's drill-down growing without end (and the dashboards' bar charts were 40 px taller than they
  were meant to be, and one still creeping). So `Fill` draws the chart in a layer taken out of the flow (`absolute inset-0`): the
  box's height comes only from its minimum and from the card stretching it. The drill-down's card is a flex column so the chart takes
  the room left. Every other chart has a pixel height. A new chart that wants a percentage height goes inside `Fill`;
  `test_chart_layout.py` fails otherwise. To check a layout change, test it at 125% and 150% zoom, not only at 100%.
- **No hole in a page.** The supporting figures sit in a grid that evens its rows and stretches the last one
  (`KpiBoard.StatGrid`); a headline with no trend says what it is where the trend would be; the brief's columns are balanced;
  bar charts take the height of the card they sit in (`CategoryBar` `Fill`); and a visual with nothing to show becomes a slim
  line across the page after the others (`ChartCard`, marked by `data-empty`) instead of an empty panel beside a full one.
  A new chart must use `ChartCard` and the shared empty state to keep this, and a row of cards should add up to the grid's
  columns (a page that doesn't leaves a gap).
- **The rows opened from a figure are the rows that count towards it.** Each figure says which rows those are
  (`population` in `dashboard/explore.py`, `tally_explore.py`): Won lists only won opportunities, Win rate the decided ones,
  Employees only active staff, Outstanding only bills with a balance, Credit notes only credit notes. Cancelled bills and
  expenses never count unless the figure is about them. The table says what it is listing, and its totals equal the tile. A
  chart's own Records button works the same way: "Open opportunities" opens the open ones, "Cancelled bills" the cancelled.
- **Drill-through rows** are read with the same filters as the chart. Sets that show money or pay row by row say who may
  open them: bills, payments and unpaid bills need billing or operational-data access; payroll and employees need
  operational-data access. The API offers no way to change a record from here.
- Amounts are shown in Indian units (lakh, crore). Chart colours come from `SERIES` and `CHART_COLORS` in
  `components/dashboard/format.ts` so a measure has one colour everywhere.

**Depends on.** The Orion warehouse (run its pipeline from the ETL page), Sign-in (`orion_dashboard_access`).

---

## ETL pipelines

**Does.** One page (rail: ETL, `/etl`) for the three ETL pipelines: **Orion warehouse** (`orion_ods` to
`orion_dw`), **Tally working copy** (Tally Prime on port 9000 to `tally_ods`) and **Tally warehouse** (`tally_ods` to
`tally_dw`). Each pipeline has a card (how it last ran, 30-day success rate, usual duration, its schedule, and buttons to
run all of it or one table) and every run is listed in a history with when it started and finished, how long it took,
whether a person or the schedule started it, who, and what it read, inserted, updated and deleted. A run opens to show
every table with its own status, time, counts and rows in the target, and where the run read from (for Tally: host, port,
company, voucher dates).

**Where.**
- ui: `pages/EtlPage.tsx` (fetches and polls), `components/etl/EtlView.tsx` (draws it), `Lineage.tsx` (the flow diagram),
  `PipelineCard.tsx`, `RunTable.tsx` (activity), `RunDrawer.tsx` (one run), `primitives.tsx`, `StatusBadge.tsx`,
  `components/ui/Drawer.tsx`, `Segmented.tsx`, `etl/format.ts`; colours `.etl-root` in `index.css`
- api: `routers/etl_router.py` (`/api/etl/pipelines`, `/runs`, `/runs/{id}`, `POST /pipelines/{key}/run`), `etl.py`
- sql: `.cursor/db/migrate_etl.sql`
- tables: `orion_ods.etl_run` (one row per run), `orion_ods.etl_run_step` (one per table in a run)

**Rules.**
- `etl.py` runs a pipeline in a background thread, table by table, calling the loader's own per-table load
  (`dw_sync.TABLES[..]["load"]`, `tally_ods._load_one`, `tally_dw.TABLES[..]["load"]`), and writes to the run and step
  rows as it goes. A run therefore carries on if the page is left, and the page follows it by polling.
- **Every start goes through `etl.start_run`.** There is no other way to load these three, so every run is recorded.
  The earlier `/api/dw/refresh`, `/api/tally/refresh`, `/api/tally-dw/refresh` and their `/{name}/load` routes were removed.
- A run's trigger is `manual` (a person, recorded as `started_by`) or `scheduled` (the automatic loader for the Orion
  warehouse). The Tally pipelines have no schedule: Tally Prime has to be open on the PC that runs them.
- One run of a pipeline at a time. The Tally warehouse also waits while the Tally working copy is running. A second
  start gets a 409 with the reason.
- The four counts mean the same for every pipeline. **Read** is the rows the source had (new, changed or the same).
  **Inserted** is new rows. **Updated** is changed rows; for a warehouse, rows that got a new version. **Deleted** is rows
  the source no longer has; for a warehouse, rows marked expired. **Unchanged** is rows already up to date. What the loader
  itself reported is kept as it came in the step's `stats`, with `current_rows` for a warehouse table.
- Each step also records the target table's row count before and after. The calendar (`Date`) is built by the load, not
  read from a source, so it is shown but not counted in a run's totals.
- A run that cannot start (Tally not reachable, no company open) is still recorded, as failed with the reason, and its
  tables as skipped. A table that fails stops the run: later tables are skipped, earlier ones keep what they loaded.
- The history is kept in `orion_ods` with the other tables the app keeps for itself, not in a warehouse schema, so
  rebuilding a warehouse or resetting the Tally copy never erases the record of what was loaded.
- The ETL segment has two flags: `etl_access` lists every pipeline and run and opens the page, `etl_write` starts a
  run. They do not depend on the warehouse or Tally flags, which only decide who can browse those tables.
- **The page.** A health sentence and a live indicator head it. Below, a flow diagram shows each hop (source to store)
  with how it last went, and it moves while a hop is running. Each pipeline has a card: the last run, a bar per recent
  run (taller is slower, red is failed), what the last run did to rows, success rate, usual duration and rows held, its
  schedule and the next check, and run buttons. A running card shows one segment per table. The activity table groups
  runs by day with the same counts; a run opens in a side drawer that leads with how it went, then the counts, the
  details, and a timeline of every table that opens for more. Row outcomes use three validated hues (inserted blue,
  updated aqua, deleted orange), never red or green, which mean failed and succeeded; each is always printed with its name.
- Each run notes the machine it ran on and the environment, so history stays meaningful across PCs.

**Depends on.** Sign-in (warehouse and Tally flags), the three loaders. **Used by.** The "warehouse last loaded" note.

---

## Database backups

**Does.** Once a day (`ORION_BACKUP_INTERVAL_HOURS`, default 24) while the API runs, takes an encrypted `pg_dump` of the four schemas (`orion_ods`, `orion_dw`,
`tally_ods`, `tally_dw`) and uploads it to a Backblaze B2 bucket. Setup, retention, restore and the reasoning are in
[backup.md](backup.md).

**Where.**
- ui: `components/etl/BackupPanel.tsx`, on the ETL page for admins only: when the last successful backup was taken and how
  big it was, the schedule and next run, why backups are blocked if they are, the last five runs, and a "Back up now" button
- api: `backup.py` (everything), `routers/backup_router.py` (`GET /api/backup/status`, `POST /api/backup/run`, admin only)
- sql: `.cursor/db/migrate_backup.sql`; `deploy/create_backup_role.sql` (the read-only `orion_backup` role, run once per database)
- tools: `scripts/backup_keygen.py` (make the key pair), `scripts/backup_decrypt.py` (unlock a backup to restore it)
- tables: `orion_ods.backup_run` (one row per backup started; no secrets and no data from the dump)

**Rules.**
- **Only the right machine backs up.** A bucket has a role (`ORION_BACKUP_BUCKET_ROLE`, `prod` or `dev`). A `prod` bucket
  is written only when `ORION_ENV=production` and the database is `orion_prod`; a `dev` bucket only when neither is true.
  A mismatch, or a bucket name that contradicts its role, stops backups and the reason is logged and shown. `backup.problems`
  holds these rules; `test_backup.py` covers them.
- **The dump never touches the disk unencrypted.** `pg_dump` is piped into `age` encryption (`pyrage`) to a file, which is
  uploaded and deleted. The server holds only the public key, so it can lock a backup but not open one. The private key
  is kept offline on another machine.
- **Nothing in the app can read a backup.** The bucket key is write-only (no list, read or delete), and the API offers status
  and "run now" only. `test_backup.py` fails if a route that reads backups is added.
- Backups run as `orion_backup`, a read-only database role, never `orion_user`.
- At the default of one backup a day every scheduled run takes one. If `ORION_BACKUP_INTERVAL_HOURS` is set under 24, a
  scheduled check skips when nothing in the four schemas was written since the last success (a fingerprint from
  `pg_stat_all_tables`, ignoring `backup_run`). "Run now" always takes one. After a restart the schedule waits out the
  rest of the interval.
- The first backup of a day is stored under `daily/` (a further one that day under `recent/`), and the first of a month is
  also stored under `monthly/`; the bucket's lifecycle rules keep each prefix for a different time.
- Failures are recorded with secrets removed and emailed to `ORION_BACKUP_ALERT_EMAIL` (every 6 hours at most); so is a
  last success older than three intervals.

**Depends on.** `pg_dump` and `pg_restore` on the PC, the `orion_backup` role, the B2 bucket. **Used by.** Nothing.

---

## Orion warehouse

**Does.** Keeps a versioned copy of the operational tables in `orion_dw`, loads itself every hour, and lets a user
browse it. It is where the history of every record lives (see "History of a record"). It is loaded, by hand or by
its schedule, as the "Orion warehouse" pipeline (see "ETL pipelines").

**Where.**
- ui: `pages/WarehousePage.tsx` (browse), `components/dashboard/WarehouseFreshness.tsx`
- api: `routers/dw_router.py`, `dw_sync.py` (the loads), `dw_auto.py` (the automatic loader), `etl.py` (runs them)
- sql: `.cursor/db/dw_schema.sql`, `grants.sql`
- tables: `orion_dw.dim_*`, `orion_dw.fact_*`. `orion_dw.load_run` is no longer written (the run history is `orion_ods.etl_run`); drop it in a later release.

**Rules.**
- SCD Type 2: a changed row closes its current version and inserts a new one; a row deleted from the ODS is
  marked `is_expired`. Exactly one row per natural key has `is_current = TRUE`.
- A fact stores the surrogate keys of the dimension versions that were current on the fact's date
  (point-in-time), not today's.
- Tables load in `REFRESH_ORDER`: dimensions first, then Bill, then the facts that point at it.
- **A revenue entry follows the current version of its bill**, not the version that was current on the entry's date:
  editing a bill makes a new version of it and rewrites its entries, so `fact_case_transaction.bill_sk` is moved to the new
  version at the next load (the entry gets a new version too, which keeps the old link in its history).
- **The calendar (`dim_date`) reaches every date a fact carries.** It always covers 2015 to three years ahead, and is
  widened to the earliest and latest transaction, driving and bill date in the data (`dw_sync._FACT_DATES`), within 1990 to
  2100 so that a mistyped year cannot add a century of rows. A fact with a date that has no calendar row would drop out of
  every report that joins to it.
- **The warehouse pages list every column** of each table, surrogate keys and point-in-time links included (`dw_sync._listing`,
  `tally_dw.dw_preview`), and every version of a record, the current one first, with its `record_status`, so a fact's key
  can be looked up in the dimension version it points at. The Employee's `monthly_salary` is still left out for readers who
  may not see it. The pages show the audit timestamps too (`allColumns` on `PreviewRecords`).
- **The privilege script is not run when there is nothing to grant.** `db_grants.needed()` reads the catalog (no table
  lock); only if a schema or table is missing, not owned, or not usable by the application's role is `grants.sql` run as
  the superuser, and it then changes only objects that are not already owned and gives up after ten seconds
  (`lock_timeout`). Changing an owner takes an exclusive lock on the table, which is what once deadlocked with autovacuum.
- Each table's columns are listed by hand in its spec in `dw_sync.py`, on both the ODS and the DW side.
- Every version carries `source_created_by` and `source_last_updated_by`, copied from the ODS row (for bills,
  `created_by` and `version_by`); a version that was deleted from the ODS carries `expired_by`, read from
  `orion_ods.record_deleted`. Those columns do not decide whether a version changed; only the table's attributes do.
- Every load is recorded in `orion_ods.etl_run` and `etl_run_step` by `etl.py`. One load runs at a time; a second is
  refused with "already running". Runs cut off by a restart are closed when the API starts.
- **Automatic loading.** A background thread in the API checks every `ORION_DW_AUTOLOAD_MINUTES` (default 60,
  0 = off) and runs a full load only if the ODS differs from when the last successful full load started
  (`source_fingerprint`: row count and newest change per table, and the number of deletions, stored on the run).
  The first check is two minutes after the API starts. A record changed twice within one interval leaves one version.
- "Warehouse last loaded" (on the Orion dashboards and the warehouse page) is the **oldest** of every table's last
  successful load (read from the steps of `etl_run_step`), since the warehouse is only as current as its stalest
  table. A one-table run counts for that table. The Orion dashboards read this warehouse, so this note is how current their figures are:
  they show what was in the warehouse at that load.
- Dimensions refer to each other by **code** (`dim_case.client_code`, `dim_employee.manager_code`,
  `dim_capability.capability_head_code`). Only facts hold surrogate keys, and a fact gets the version of each
  dimension that was current on its date. So when a capability's head changes, the capability gets a new version,
  earlier transactions keep pointing at the version that was current for them, and a report can ask who headed it then.
- Client `billing_name`, `gstin` and `billing_address` are versioned. The first time those columns were added, the
  current versions were filled in place so the load did not report every existing value as a change.

**Depends on.** Operational Data, Billing. **Used by.** The Orion dashboards read `orion_dw` (see "Orion dashboards").

---

## Forecast (Orion and Tally dashboards)

**Does.** A **Forecast** tab on both dashboards (`/dashboard/orion/forecast`, `/dashboard/tally/forecast`): where a figure is heading if the business keeps its
present pace. For each figure it gives the expected total, and a likely range, for the next **1 month, 3 months, 6 months, 12 months and 3 years**, set against the same length
of time just gone; a chart of what happened and what is expected, with a range that widens with distance; the year-by-year totals (financial years, the months done plus the months
still to come); what is behind it (recent pace, growth on a year ago, the pace the forecast expects, how much it moves, the usual pattern through the year); and how it was worked
out and how well it would have done. Orion forecasts **revenue, billed, cash collected, cost and margin** and can be narrowed to a client, a business domain or a case; Tally
forecasts **billed, revenue, GST, documents and credit notes** and can be narrowed to a company, client, document type, income line or cost centre. A slider asks "what if the pace is
5% a year faster or slower than the trend" (it only scales the figures on the screen), and Export saves the monthly forecast as a CSV.

**Where.**
- statistics: `backend/app/forecast.py` (pure Python: no database, no numeric library, no new dependency)
- feeds: `dashboard/forecasting.py` (Orion, from the same monthly functions the other tabs use: `trend`, `cash_trend`), `tally_forecast.py` (Tally, from `tally_dashboard._monthly` and `_document_trend`)
- api: `GET /api/dashboard/forecast` (`routers/dashboard_router.py`, registered before `/{view}`) and `GET /api/tally-dashboard/forecast`
- ui: `pages/dashboards/ForecastPage.tsx` (both tabs; it stands outside the dashboard shell), `components/dashboard/ForecastBoard.tsx`, `forecastApi` in `api/client.ts`, the types in `types.ts`;
  the tab is a `standalone: true` entry in `dashboards/registry.ts`
- Copilot: `ai/tools/forecast.py` (`get_forecast`, read-only)

**Rules.**
- **It learns from every month, not the period on screen.** A forecast of a year ahead from "this financial year" would be nonsense, so the page ignores the period filters of the other tabs; only
  who and what (client, domain, case ...) narrow it, and they live in the address like other dashboard filters.
- **Cleaning first** (`forecast.prepare`): leading empty months are dropped; **the month in progress is left out** (it is not a whole month); a one-month spike or a month with no data
  is smoothed for fitting and counted; and a **level shift** (a jump between two months far bigger than months usually move, such as a large contract ending) is found, so the models learn from the
  new level only (when at least 6 months have passed since it; sooner than that the range is widened and the page says so). Each of these is said on the page.
- **Several simple models, chosen by testing** (`MODELS`): the recent run-rate, a damped trend (Holt), a trend line, and, with two full years, a seasonal damped trend (Holt-Winters)
  and last year's pattern grown at the recent pace. Each is **back-tested**: fitted on the past up to a month, asked for the next months, scored against what happened, from many starting months.
  The best three are blended, weighted by how well they did. No model is trusted because it is sophisticated.
- **The range is measured, then stretched where it must be** (`_sigmas`): the error spread at each distance ahead comes from the back-test; beyond what was tested it grows like a random walk; it
  is widened when the history is much shorter than the horizon, and by an allowance for the pace of growth itself being wrong (6% of the level per year, 10% when under 18 months of history).
  If the back-test shows the range held less than 70% of the months it claims 80% for, it is stretched until it would have. Ranges for a total (three months, a year) combine the months'
  spreads allowing that neighbouring months' errors move together (`CORR`), so a quarter is not as wide as three worst months added.
- **Skill is honest.** The forecast is compared with the better of two simple guesses (next month equals this month; next month equals the recent average). It is called "better than a simple guess"
  only with at least `MIN_TESTED` tested months. **Confidence** is `very_low` under 9 months of history, `low` under 18 months or when it did no better than the simple guess,
  `medium` under 36 months, else `high`; a recent level shift, or a range that fits past months badly, lowers it one step. The reasons are shown. The three-year figure carries a plain "indicative
  only" note when there is under two years of history.
- **Margin is revenue less cost**, taken from the two forecasts (`forecast.difference`), never forecast separately, so the page always agrees with itself; its spread allows that costs move with revenue.
- A figure that cannot be negative is never forecast below zero.
- Nothing is saved. A forecast is worked out on request (about 0.2 s for Orion, 0.4 s for Tally on the development data) from the warehouse, so it is as current as the warehouse (see "Orion warehouse").

**Depends on.** The Orion warehouse (`orion_dw`) and the Tally warehouse (`tally_dw`), the dashboard engine's monthly series, and sign-in (`orion_dashboard_access` for the Orion tab and
tool, `tally_dashboard_access` for the Tally tab and tool; the routes use the same dependencies as the other dashboard routes).
**Used by.** The Copilot (`get_forecast`: "what will revenue be next year?").

---

## Tally working copy, warehouse and dashboards

**Does.** Copies the company's Tally Prime books into the database and reports on them: billing overview,
billing activity, credit notes, income mix, clients and debtors, books snapshot.

**Where.**
- ui: `pages/TallyDataPage.tsx`, `TallyOdsPage.tsx`, `TallyDwPage.tsx` (both browse only), `TallyDashboardPage.tsx`,
  `pages/dashboards/tally/*`, and the shared `components/dashboard/*` pieces (`FilterDock`, `DashboardBrief`, `KpiBoard`, `MetricCard`)
- api: `routers/tally_router.py`, `tally_client.py`, `tally_ods.py`; `routers/tally_dw_router.py`, `tally_dw.py`;
  both are loaded as pipelines by `etl.py` (see "ETL pipelines");
  `routers/tally_dashboard_router.py`, `tally_dashboard.py`, `tally_insights.py`, `tally_kpi_help.py`
- sql: `.cursor/db/tally_ods_schema.sql`, `tally_dw_schema.sql`
- tables: `tally_ods.*`, `tally_dw.*`. See `.cursor/db/tally_ods_data_model.md` and `tally_dw_data_model.md`.

**Rules.**
- Tally is read-only from Orion: the app only asks Tally for data, over its XML server
  (`ORION_TALLY_HOST`, `ORION_TALLY_PORT`). The company must be open in Tally.
- `tally_ods` is SCD Type 1 (latest value wins). `tally_dw` is built only from `tally_ods`, as SCD Type 2.
- Every billing tile can be opened (`tally_explore.py`, `GET /api/tally-dashboard/explore/{figure}`) by year, month, client,
  document type, company, income line and cost centre, with the billed documents behind it. The books tiles open by account
  group and ledger. It uses the same `_sales_where` filter as the dashboard, so the totals agree.
- The dashboards read `tally_dw`, so they change only after a Tally load **and** a warehouse load.
- Both loads are started from the ETL page. The Tally warehouse refuses to start while the Tally working copy is
  loading, since it reads it.
- The Tally and Orion sides are independent: no table in one references the other. Billing no longer uses Tally.
- `tally_insights.py` is pure (no database) and is unit-tested; keep it that way.
- Every Tally KPI has plain-language help in `tally_kpi_help.py`; a new KPI needs an entry.

**Depends on.** Sign-in (`tally_*` flags). Tally Prime running on the office PC.

---

## AI Copilot

**Does.** An assistant built into every screen. A person asks in plain words ("why did revenue fall last month?",
"who owes us the most?", "create a receivables report", "remind me to chase Acme next week", "delete client CL-0007")
and it looks the answer up in Orion's own data, shows it as figures, tables and charts with the sources, and can do
things for them: create, change or delete records, export data, make a PDF report, email a file, set a reminder, open a
page with filters applied, switch light/dark or theme. It also surfaces a few things worth a look (a drop in revenue,
money unpaid over 90 days, documents about to lapse) and suggests questions for the page the person is on.

**How it answers (local first).** Cheapest and most private first: (1) **Orion itself**: rules recognise common requests and the
tools work the answer out from real data, written in plain words, with no model; (2) **a model on this computer** (Ollama) for
anything open-ended; (3) **a cloud model** (OpenAI or Anthropic) only when the local model could not do it and the server, the
organisation's policy and the person all allow it. It works with no model and no key. Each answer shows which of the three made it.
Setup, privacy and troubleshooting: [ai-setup.md](ai-setup.md). Routing tests: [ai-routing-test-report.md](ai-routing-test-report.md).

**How a very small model is still useful.** For a data question the rules do not recognise, the local model only fills in a short form (which intent, metric, period, record type, name),
checked against the question's own words; Orion does the lookup and writes the answer. Free conversation with tools is the last resort, and a reply that looked nothing up is never shown as an answer.

**How a person uses it.**
- The **Copilot** button in the top bar (and the round button in the corner) opens a panel beside the page (over the page
  on a phone). `Ctrl+J` opens and closes it; `Ctrl+K` opens the command palette (ask anything, jump to a page, run a
  command). "Ask AI" buttons on the dashboards, Billing, Receivables and Documents start a conversation about what is on
  screen. The page's tab, filters and open record go with each question (the person can switch that off in the panel).
  A small **amber dot** on the top-bar button means the Copilot has at least one warning or critical finding (a drop in
  revenue, money long overdue, a document about to lapse); hovering the button says how many, and the panel's welcome
  view lists them. The dot is hidden while the panel is open.
- **Two sources of figures.** The Copilot reads Orion's own records (bills, payroll, cases, receivables, documents) and the Tally
  books (billed documents, income lines, credit and debit notes, Sundry Debtors, closing balances). They are kept separately and can
  differ, so its answers say which they came from ("in the Tally books"), it never joins them into one number, and a question that
  names Tally, the books, a credit note or a Sundry Debtor is never answered from Orion's records. The Tally tools
  (`ai/tools/tally.py`: `get_tally_summary`, `get_tally_metric`, `compare_tally_periods`, `get_tally_top_clients`,
  `get_tally_income_mix`, `get_tally_debtors`, `get_tally_credit_notes`, `get_tally_books_position`) are read-only, offered only to
  a person with the Tally dashboard, and call the same functions the Tally dashboard page does (`tally_dashboard.py`), so a figure
  matches the page. Sundry Debtors are the books' closing balance at the last warehouse load, not aged receivables (that is
  `get_receivables`); balances are never added into one total. On a Tally dashboard "Ask AI" and the questions typed in the
  panel use the dates and filters on screen.
- Answers stream in, with the steps it took shown ("Looking things up...", then "Checked 2 things"). **Stop**
  (button or `Esc`) ends one early, **Regenerate** asks again, **Copy** copies it, and an error offers **Try again**.
- A change is only ever *prepared*: a confirmation card shows exactly what will happen (built by the server from the
  checked request, in red for a delete), and nothing happens until the person presses the button.
- Conversations are saved (new, rename, search, delete, filter by kind, continue). Settings > **AI Copilot** has the
  switches (use it, remember conversations, show what is worth a look), a plain explanation of data and privacy,
  "clear my history", a list of what the Copilot has done for the person, and (admins) the provider and usage.

**Where.**
- ui: `ai/AssistantContext.tsx` (the conversation layer: send, stop, regenerate, confirm, history), `ai/transcript.ts`
  (stream events into messages), `ai/pageContext.ts`; `components/assistant/` (`AssistantPanel`, `MessageView`,
  `Blocks` (metric cards, tables, charts, files, reminders), `ConfirmCard`, `Markdown` (safe renderer), `Composer`,
  `Welcome` (insights, suggestions), `HistoryList`, `CommandPalette`, `Launcher` (top-bar button, corner button,
  `AskAiButton`), `AiSettings`); mounted in `components/Layout.tsx`; client in `api/client.ts` (`aiApi`) with types in `types.ts`
- api: `routers/ai_router.py`; `ai/` (`config.py` every model name, limit and the key; `providers/` (`base.py`
  `AIProvider`, `ollama_provider.py` (`LocalProvider`), `openai_provider.py`, `anthropic_provider.py`, `scripted.py` for tests); `prompt.py` the fixed rules;
  `orchestrator.py` the conversation loop; `routing/` (`classifier.py` category A to J by rules, `intents.py` the requests Orion answers itself, `compose.py` those answers' wording, `engine.py` local first, quality checks, bounded retry, escalation, `policy.py` the cloud decision, `sensitivity.py`, `pseudonym.py`, `guards.py` circuit breakers, rate window and cost); `tools/` (`core.py` registry, validation, permission, audit; `tally.py` the Tally books; `analytics.py`
  dashboard figures; `records.py` records, bills, documents, calculate; `actions.py` changes, reports, exports, reminders,
  navigation); `safety.py` untrusted-data wrapping, context cleaning, number checking, calculator, rate limit; `periods.py`
  dates and the Indian financial year; `insights.py`; `reports.py`; `store.py`); `entity_service.py` (the record rules shared with the generic forms)
- tables: `ai_conversation`, `ai_message`, `ai_audit`, `ai_pending_action`, `ai_file`, `ai_task`, `ai_user_setting`,
  `ai_insight_state`, `ai_usage` (all in `orion_ods`, file `.cursor/db/migrate_ai.sql`); `app_user.ai_access`
- settings: the `ORION_AI_*` variables and, only if cloud is used, `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in `.env` (see `.env.example` and ai-setup.md)

**Rules.**
- **The model never touches the database.** It can only ask for a registered tool (`ai/tools`), with arguments checked
  against the tool's schema (types, ranges, enums, lengths, no extra keys). There is no tool that runs SQL, calls an
  arbitrary endpoint or deletes in bulk.
- **Permissions are the person's own.** Each tool declares `needs(user)`; the model is offered only the tools the person
  may use, and the check is made again when a tool runs and again when a confirmed action runs. Dashboard figures need the
  Orion dashboard flag, records need the operational-data flags (and write for changes), receivables and bills need Billing,
  documents need Documents (Confidential ones need the write flag). Asking the Copilot to "act as admin" changes nothing.
  `app_user.ai_access` (Admin > Users, default on; admins and editors and viewers alike) lets someone use it at all.
- **Numbers come from tools, never from the model.** Figures are the dashboard engine's raw totals, so they are the same
  as on the dashboard; arithmetic goes through the `calculate` tool; tables, charts and metric cards are made by the
  server and the model only says where to place them (`{{block:ID}}`), so it cannot invent a chart. After each answer the
  figures it states are checked against what was retrieved and anything that cannot be matched is flagged to the person.
  With no data it says "I couldn't find data matching that request."
- **Everything retrieved is untrusted.** Tool results are wrapped as data the model is told never to obey; page context is
  whitelisted and cleaned; a document's text or a client's name cannot give it instructions. Private employee columns
  (bank, ID numbers) are never returned.
- **A change waits for a human.** Create, update, delete and email are prepared into `ai_pending_action` (20 minutes),
  shown on a card, and run by `POST /api/ai/actions/{id}/confirm`, which claims the action once, re-checks permission
  and runs it through `entity_service` (the same rules as the record forms, including "a revenue entry that belongs to a
  bill is not editable"). Low-risk actions (a reminder, an export, a report, a page opening, a theme change) run at once.
- **Everything is audited.** Each tool call, refusal, denial, invalid request, confirmation and cancellation is a row in
  `ai_audit` (who, when, conversation, tool, entity, arguments trimmed, result, whether confirmation was needed and given).
  A person sees their own in Settings; an admin sees everyone's (`GET /api/ai/audit`).
- **Limits.** Per person: a number of questions a minute (`ORION_AI_RATE_PER_MINUTE`), a day (`ORION_AI_DAILY_REQUESTS`)
  and output tokens a day; one answer is written at a time. Cloud use has its own limits: a monthly budget (0 means none), a daily
  allowance per person and a request rate, with an estimated cost recorded per answer. Local answers are one at a time by default. Older turns
  are summarised (by the local model only) so each request stays small.
- **Failures are plain.** The person sees "Something went wrong while analysing your data. Please try again." and the
  technical error goes to the server log. With no local model running, the panel says so, keeps answering what Orion can answer
  itself, and never turns to a cloud model unless the person chooses it for that one question.
- **Private data stays here by default.** The organisation's policy (`ai_policy`: local only, no application data to cloud, local first
  with approved fallback, cloud for eligible tasks; default local only) and the person's own choice (`ai_user_setting.allow_cloud`, default off)
  must both allow cloud, as must the environment (`ORION_AI_CLOUD_ESCALATION`, a key, a model, a budget). A request that is sensitive
  (credentials, Aadhaar, PAN, bank, card, IFSC, GST, phone, email, pay) is never sent. What is sent is minimised: the question and the
  page's filters (not the conversation, not who is asking) and retrieved figures with names replaced by labels. `policy.decide` lists
  every check and which one blocked, which is what `POST /api/ai/route/explain` and the routing log show.
- **Escalation is by objective checks, never by the model's confidence**: an empty answer, figures stated with no lookup, figures that do
  not match the tools' results, or repeated invalid tool calls. Retries, timeouts and a circuit breaker per provider bound it.
- The providers are behind `AIProvider` (stream, complete, structured, health, capabilities); adding one is a class in `ai/providers/`
  and a name in `providers/__init__.py`. Keys are read on the server only and are never sent to a browser. `ORION_AI_LOCAL_PROVIDER=scripted`
  is a deterministic stand-in for tests; it is refused when `ORION_ENV=production`.
- `ai_route_log` holds one row per answer (category, who answered, model, reason codes, attempts, time, tokens, estimated cost,
  outcome). It never holds the question, the answer or data.
- Insights are rules over real data (no model is involved) and at most five are shown; a person can hide one for a week.
- A conversation, its steps, blocks and confirmation results are stored as `parts` on `ai_message`; a confirmation's result is
  a small separate assistant message that the screen folds into its card (`ai/transcript.ts` `present`).

**Used by.** It reads the dashboards (`dashboard/`), records (`entity_service`, `entities`), billing and receivables,
documents, mail and reports. Changes there can change what the Copilot can answer; see change-impact.md.

---

## AI help in the screens

**Does.** Beyond the Copilot panel, five screens have an optional AI button that does one job for the person looking at that
screen. Each one produces a **draft or a suggestion** for the person to read and use; nothing is saved, sent or filed until
they do it.

| Screen | Button | What it does | What the model is given |
|---|---|---|---|
| Letterhead, letter editor | **Write with AI** | Writes the body of a letter from a few points, or changes the selected text (tone, shorter, fuller, spelling and grammar, translate into Hindi, Gujarati, Marathi and others). The answer is shown first, then replaces the selection or goes in at the cursor, and Ctrl+Z undoes it. | the points or the text, nothing else |
| Billing, Outstanding, "Send reminder" | **Reword with AI** (tone: polite, friendly, firm, final notice) | Rewrites the reminder's wording. | only the wording and "N bills, the oldest D days old": never a client name or an amount. The client, bill list, total and bank details are put in by the application afterwards. A reply that dropped or repeated any of them is thrown away. |
| Document Center, upload | **Suggest details** (per file) | Proposes a title, kind, document and expiry dates, tags and a one-line description from the start of the file. | the first 6,000 characters of text, or only the file name if none could be read (the screen says so) |
| Operational Data, a record form | **Fill from text** | Reads a pasted email or message and proposes values for the plain fields. | the pasted text and the list of fields it may fill |
| ETL, a run's drawer | **Explain this failure** | Says in plain words what happened, the likely cause and what to try. | the run's name and its error messages |

**Rules.**
- One gate for all of them, `ai/assist.py`, which uses the Copilot's own policy (`routing/policy.py`): a model on this computer first;
  a cloud model only when cloud AI is switched on, the organisation's policy allows it, and the budget and rate have room; **and the person
  says yes for that one request** ("send this once"). The yes is never remembered. A policy that sends no application data to the cloud
  blocks every job that carries any; a wording-only job (the reminder) is not blocked by it.
- Who may press it is who may do the underlying task: letterhead write, billing write, documents write, operational data write, ETL access.
  A person whose AI access is off, or who has switched the Copilot off in their settings, gets no AI help anywhere.
- At most 20 AI jobs a person a minute across all features. Nothing that was asked or answered is logged; the route log keeps only the
  kind (`assist_letter_draft`, `assist_form`, ...), model, time and tokens.
- What comes back is never trusted: letters are rebuilt from paragraphs and lists and then cleaned by `letterhead.clean_html`; document
  kinds must be on the category list and dates valid; form values are coerced to the field's type and options. Fields that are lookups
  (another record's code), computed by the form, read-only or private (the Employee's Aadhaar, PAN and salary) are never offered to a model.
- A model is told that the letter, document or email is data and that instructions inside it are not to be followed.

**Files.** `backend/app/ai/assist.py` (the gate), `backend/app/ai/features.py` (the five jobs),
`POST /letterhead/ai`, `POST /billing/receivables/{client}/reminder/ai`, `POST /documents/ai/suggest`,
`POST /entities/{name}/ai/fill`, `POST /etl/runs/{id}/explain`;
`frontend/src/components/ai/{AiTask,FillFromText}.tsx`, `components/letterhead/LetterAiModal.tsx`, and the buttons in
`ShareModal.tsx`, `documents/UploadModal.tsx`, `OperationalDataPage.tsx`, `etl/RunDrawer.tsx`.
Tests: `test_ai_assist.py` (gate and jobs), `test_ai_routes.py` (permissions, bad requests).

**Used by.** Letters, receivables, the Document Center, the generic record forms and the ETL page: a change to what one of
them accepts changes what its AI help may propose (see change-impact.md).

---

## Clients

**Does.** One page for each client: who they are, the cases we run for them, the people we deal with and, for someone who may see billing, what has been billed to them, what has come in
and what is still owed, with how old it is. A directory lists every client (search; Active, Owing, Everyone), with what each owes. It is read only: a client, a case or a person is changed
in Operational Data, a bill or a payment in Billing, and the buttons on the page lead there. It is in Data (`/data/clients`, `/data/clients/CL-0001`), reached from Orion data ("Clients"), from
a client's name on the Outstanding page and from a group's members.

**Where.**
- ui: `pages/clients/ClientsPage.tsx` (the directory, and `ClientMark`), `ClientPage.tsx`; the routes are in `workspaceRoutes.tsx` (`dataRouteTree`) and the area is Orion data (`areaOf`)
- api: `routers/clients_router.py` (`GET /api/clients?search=`, `GET /api/clients/{code}`), `clients.py` (everything it reads); `billing.list_bills(client_code=...)` (the bill filter added for it)
- tables: none of its own. It reads `orion_ods.client`, `case`, `contact`, `employee` (people on a case) and, through `billing.py` and `receivables.py`, bills and payments.

**Rules.**
- Seeing a client needs operational-data access (`require_ods`). **The money is only for people who may see billing** (`auth.can_access_billing`): without it the answer has `money: null` and no
  figure or bill is read at all; the directory then has no "owed" either.
- **No money is calculated a second time.** What is owed, how old it is and its age bands are the receivables report's own figures for the client (`receivables.client_statement`); billed, received and
  credited are sums of the same bill rows the Bills register lists (cancelled bills are left out); `backend/tests/test_clients.py` checks both, and that a person without billing gets none.
- A bill number on the page is a `BillNumber` (a card on hover, the bill in a new tab).
- **Its buttons open the form for this record.** "Change details" opens that client's (or case's, employee's) Edit form with the record already chosen and loaded, "Add a case" arrives with the client already
  filled in, and "Add an expense" on a case with the case; each shows the usual change warning first and has a way back to the page it came from. The address is
  `/data/operational?intent=change&entity=Case&mode=create&fill=client_code:CL-0001&return=/data/clients/CL-0001&returnLabel=Client` (`mode=edit&record=CODE` for a change); a `fill` field must be one the
  record type's form has, and `return` must be a page of Orion data (`components/profile/links.ts` builds it, `OperationalDataPage` reads it).

## Cases, employees and accounts (their pages)

**Does.** The same kind of page as a client's, for the other things people ask about by name. A **case's page** (`/data/cases/CS-0009`): the site, the people placed on it, the contacts for it (and its client's
main contact), the deposits (EMDs) and the expenses against it and, for someone who may see billing, what it has billed and what is still owed. An **employee's page** (`/data/employees/EMP-0140`): who they are,
the case and client they work at, who they report to and who reports to them, the contacts they look after and, for someone with bank access, their latest salary lines. An **account's page**
(`/admin/users/493`, administrators only): who it is, what it may do in each part of Orion in words (Can change / Can see / No access), when and from where it was last used, and the tasks on it. Each has a
directory (`/data/cases`, `/data/employees`) with a search, reached from "Look something up" on Orion data; the account page from "Open the account page" under Admin > Manage user. All are read only.

**Where.**
- ui: `pages/clients/CasesPage.tsx`, `CasePage.tsx`, `EmployeesPage.tsx`, `EmployeePage.tsx`, `UserPage.tsx`; the pieces they and the client page share are `components/profile/parts.tsx` (`Mark`, `Section`, `Fact`, `Nothing`, `StatusPill`)
- api: `routers/cases_router.py`, `routers/employees_router.py` (`/api/cases`, `/api/employees`), `GET /api/users/{id}/overview` in `routers/users_router.py`; the readers are `cases.py`, `employees.py`, `user_overview.py`; `billing.list_bills` takes `case_code`
- tables: none of its own.

**Rules.**
- Cases and employees need operational-data access (`require_ods`). A case's **money** (billed, received, owed, its bills) is read only for someone who may see billing, and what it owes is the receivables report's
  balances of that case's own bills (never billed minus received). An employee's **pay** is read only for someone with bank access (`auth.can_access_bank`). **Nothing private is ever selected**: `employees.py`
  never names the Aadhaar, PAN or agreed-salary columns (a test reads its source for them), and their papers are opened in the Document Center. The directory has no pay at all.
- The account page is **administrators only** (`require_admin`), shows no secret (the cookie's token is never selected, a session is shown by its own number) and changes nothing: roles, access and passwords stay under Manage user.
- `backend/tests/test_profiles.py` checks who sees what for all three.

## Tasks

**Does.** The team's work in one place: a Jira-style task tracker with personal to-do lists. Anyone who signs in uses it (Team > Tasks, `/tasks`); what a person may do in a
project depends on their role in it. A **project** (key such as `OPS`) holds tasks numbered `OPS-1`, `OPS-2`…; each task has a status, an assignee, a reviewer, a priority, a type, dates,
an estimate, labels and a history. Tasks are shown as a **board** (a column per status, drag to change status or place), a **list** (a table with a filter on every column), a **sprint
plan**, a **calendar** and, for each person, **My work** (their tasks by when they are due, what waits for their review, what they raised and watch) and their own **to-do lists**.

**In Lumen** My work opens on a greeting and one sentence about the day (what is overdue, what is due today, what waits for the person's review), then the same figures on coloured tiles; each group of tasks has a count
chip (red for overdue, amber for due today) and roomier rows; the board's columns are rounder glass panels. Nothing about what can be done changes.

**Where.**
- ui: `pages/tasks/` (`TasksPage` the frame with the sections, quick finder and "New task"; `MyWorkPage`, `TodoPage`, `ProjectsPage`, `ProjectPage`, `ReportsPage`, `InboxPage`),
  `components/tasks/` (`TaskDrawer` one task opened over any page via `?task=KEY`, `TaskPanels` comments/files/checklist/time/links, `NewTaskModal`, `BoardView`, `ListView`,
  `CalendarView`, `SprintsView`, `TemplatesView`, `ProjectSettings`, `FilterBar`, `TaskRow`, `PersonSelect`, `TasksBell` the bell in the top bar), `tasks/taskUi.tsx` (priority, status, person,
  duration and date helpers), `tasks/useOpenTask.ts`, `tasks/useTaskPeople.ts`, `context/TasksContext.tsx` (the bell and rail numbers, looked at every minute)
- api: `routers/tasks_router.py` (`/api/tasks/...`); the writers are split by the tables they own: `tasks.py` (projects, members, statuses, tasks, reviews), `task_items.py` (comments, watchers,
  checklist, links, time), `task_files.py` (attachments), `task_notify.py` (the inbox and reminders), `task_todo.py` (personal lists), `task_sprints.py`, `task_templates.py` (templates and the
  hourly job that makes the repeating ones), `task_views.py` (board, calendar, reports, search, saved filters), `task_common.py` (vocabulary, who may do what, the history every change leaves)
- sql: `.cursor/db/migrate_tasks.sql`
- tables: `orion_ods.task_project`, `task_member`, `task_status`, `task_sprint`, `task_template`, `task`, `task_comment`, `task_activity`, `task_file`, `task_attachment`, `task_watcher`, `task_link`,
  `task_record_link`, `task_checklist_item`, `task_time_log`, `task_review`, `task_notification`, `task_saved_filter`, `task_todo_list`, `task_todo`. None is loaded into the warehouse.

**Rules.**
- **Who may do what** (`task_common.role_in`): a project is **Company** (everyone who signs in sees it and works in it as a Member, unless they were added with another role, for example as a Viewer) or **Private** (a person outside it is not even told it exists:
  the answer is "not found"). A member is a **Manager** (runs the project: members, statuses, sprints, templates, archive), a **Member** (creates and changes tasks) or a **Viewer** (reads, and comments in
  a company project). An Orion **admin** is a manager of every project. A project always keeps one manager. An **archived** project is read-only, but everything in it can still be read.
- **Statuses** are per project and each has a **kind**: to do, in progress, in review or done. The kind, not the name, decides what a status means (done means resolved). A project keeps at least a to-do and
  a done status; a status that holds tasks cannot change between done and not done or be deleted without moving them; a status may have a **limit** on how many tasks it holds at once (shown on the board).
- **A task is finished** only through the move to a done status, with how it ended (Done, Won't do, Duplicate, Cancelled) and, if the project says so, after a review. It cannot be finished while a task
  that **blocks** it, or one of its sub-tasks, is open. Reopening clears the resolution. Tasks are **never erased**: "Delete" (a manager, or the person who raised it) hides the task and its sub-tasks, the history is kept, and a manager can restore it (`POST /api/tasks/KEY/restore`; there is no screen for that yet).
- **Review.** Sending a task for review names a reviewer who is **not the assignee**; the reviewer (or a manager) **approves** (the task is done) or **asks for changes** (a reason is required; it goes back to work).
  The person who asked can withdraw it. A project can **require review**: then a task can only be finished by an approval. Every review and its decision is kept.
- **Changes are checked against what the person saw**: a save carries the time the task was last changed (`expected_updated`); if someone else changed it meanwhile the save is refused with 409 and the screen
  reloads, so two people never silently overwrite each other. Creating a task, a comment and a to-do take an `Idempotency-Key`, so a double click or a retry makes one.
- **History** (`task_activity`) records every change, comment, file, link and review with who and when, and cannot be changed or deleted (a trigger); **comments** can be edited (marked) or deleted (a marker stays).
- **Files** are checked like the Document Center's (`documents.check_file`: kinds, size, content), kept once per different file (sha256) in `task_file`, shown in the browser only when a picture or a PDF, otherwise
  downloaded, always with `nosniff`. A person who cannot see the task cannot fetch its file. Removing the last attachment that uses a file removes the bytes.
- **Mentions** in a comment (`@[Name](user:ID)`) notify that person and add them as a watcher; the text is rendered by the safe Markdown renderer, never as HTML. **Watchers** (the assignee, reporter, reviewer, commenters and
  anyone who presses Watch) are told of changes. A person is never notified of their own action. **Reminders** (late and due in three days) are worked out when the bell is opened, not stored.
- **Links**: tasks link as blocks / relates / duplicates (a link that would make a task block itself through others is refused); a task can also point at an **Orion record** (bill, case, client, employee, opportunity, EMD,
  expense, document) only by someone who may see that kind of record, and the label is saved when it is linked. Sub-tasks have a parent; an epic groups tasks.
- **Time**: people log minutes against a task for a day (not in the future); the task shows logged against estimated time. Estimates are typed like `90`, `1h 30m`, `2d` (a day is 8 hours).
- **Sprints**: a project has at most one **Active** sprint. Completing it sends what is not done to the backlog or to a planned sprint; the burndown (story points, or tasks without points) is drawn against a straight line.
- **Templates and repeating tasks**: a template is a task ready to make (checklist, assignee, reviewer, labels, due after N days); with a schedule (daily, weekly, monthly, yearly, every N) it makes the task by itself.
  An hourly job (`task_templates.start`) makes the **latest** missed run only (a computer that was off does not flood the project), a short month uses its last day, and the next run is worked out from the schedule, never
  from when the job ran.
- **To-do lists** are private to each person (nobody else, not even an admin, can read them through the API): an Inbox, My day (items for today), custom lists, a due date, notes. An item can be turned into a task in a
  project (given to the person; the item is ticked and linked). Finished items are kept 14 days; at most 500 open items and 30 lists.
- **Saved views** keep a set of filters for a project, for the person or shared with the project (a manager shares). The list's per-column filters are the usual table filters.
- **Not loaded into the warehouse or the Copilot yet.** Not yet: e-mail digests, automation rules, custom fields, importing from Jira/CSV, a "make a task" button on bills, and real-time updates (the bell and lists look again every minute and when something is changed here).

**Depends on.** Sign-in (`app_user`: names, photos), `documents.check_file` and `idempotency`, and for record links the access flags of the kind of record.
**Used by.** Nothing yet; later a bill, a case or a document-expiry reminder can create tasks through `tasks.create_task`.

---

## Messages

**Does.** Chat between people in Orion, in real time: one to one, and in groups of up to 50 people, with voice notes and (one to one) voice, video and screen-sharing calls.

- **The screen** (both looks; Lumen adds glass, gradients and rounder shapes through the `chat-*` hooks in `lumen.css`): on the left the conversations, on the right the open one, and the details as a drawer over it.
  The list has a title with a **new message** button (it opens the list of everyone in Orion, first; the list is not always on show, only when asked for, while searching and when there are no
  conversations yet), a search box, **Around now** (who is online, one tap to open them), All / Unread / Archived, and rows with a presence dot, a bold name and a count when unread, and a small picture in
  the preview for a call, voice note, photo, video or file ("typing…" and "Draft:" take its place). The thread has a header with a large photo and presence, **Call** and **Video** buttons, search, details and options;
  15px bubbles; **one-tap reactions** (👍 ❤️ 😂 😮 🙏), reply and more when pointing at a message; call lines as quiet pills (the call-back button shows when pointed at); and one rounded message bar with
  attach, emoji, AI help and a microphone that becomes send when there is text. Opening Messages with nothing selected shows a welcome and the people to reach, each with message, voice and video buttons.
- **Conversations.** A list with photos, the last message (or what you were typing), time, unread counts and who is online. Kept-at-the-top
  conversations come first; *All*, *Unread* and *Archived* filter it; one box finds people by name and messages by what was said (only in
  your own conversations), and opening a message result jumps to it. A person can mute a conversation (no pop-up, not in the badge on the
  rail), keep it at the top or archive it; a new message brings an archived one back. These choices are each person's own.
- **Messages.** Sent at once and shown as sending, sent, read (the other person has opened it) or failed with Retry and Discard; the same
  send arriving twice (a retry) is stored once. Runs of messages from one person within five minutes are grouped; days are separated; the
  conversation opens at the first unread message with a "N new messages" line, stays put while you read older ones, and offers
  "Latest messages" and a count of what arrived meanwhile. History loads 40 at a time as you scroll up and keeps your place.
- **Each message** can be replied to (the quote jumps to the original), reacted to with an emoji (up to six per person), copied, forwarded to
  another conversation or person (with its file), pinned to the conversation (up to ten; the newest shows in a bar at the top), and, if it
  is yours, edited (marked "edited") or deleted for both people (a "This message was deleted" marker stays, with the text and file gone).
  Web addresses become links (http and https only). A message is up to 4,000 characters.
- **The box.** Grows with what is typed; Enter sends and Shift+Enter starts a line (on a phone Enter starts a line); Esc cancels a reply or an
  edit; Up in an empty box edits your last message; Ctrl+F searches the conversation. Emoji go in at the cursor. Files are attached with the
  paperclip, by drag-and-drop or by pasting an image, checked (12 MB; photo, video, PDF, Office, text, zip), previewed and sent with progress.
  What was typed is kept per conversation until it is sent.
- **Live.** Typing, new messages, edits, deletes, reactions, pins and read state arrive over the WebSocket; after a dropped connection the
  conversation fetches what it missed. Presence shows who is online; there is no "last seen".
- **AI help (optional).** The sparkle button in the box can rewrite the draft (more professional, friendlier, shorter, more casual), translate
  it, suggest three replies or summarise the conversation. It only produces text to edit; nothing is sent for the person. It runs on a model on
  this computer when there is one; otherwise a cloud model only when the Copilot's policy allows it (see "AI Copilot") **and** the person says
  yes to that one request. Only this conversation is given to it, as "Me" and "Them" without names. What was said is never logged.
- **Groups.** *New message* > *New group* (also on the welcome screen) asks for a name (up to 60 characters) and the people; whoever makes it is its admin. A group is a conversation like any other
  (messages, replies, reactions, pins, files, voice notes, search, forwarding, mute / keep at the top / archive), drawn with its own picture (the first letters of its name), the name of whoever said each
  run of messages, "N people · M online" and who is typing in the header, and, in the details drawer, who is in it. **Admins** add people (they can read everything said before they joined, and the dialog says so),
  remove people, rename the group and make someone an admin or take that back; **anybody** can leave (the last admin leaving hands the group to whoever has been in it longest; the last person leaving deletes it); an admin
  can delete it for everyone. Joins, leaves, removals, renames and new admins are lines in the conversation ("Priya added Rahul") that nobody wrote and nobody can edit, delete, react to, pin or forward, and that never
  count as unread. A message in a group shows as read for its sender when everybody else has read it. Calls and AI help are one to one only.
- **Voice notes.** The microphone button (where the send button is while nothing is typed) records: a timer, the loudness as it happens, a bin to throw it away and a send button.
  A note is shown with play and pause, a picture of its loudness that fills as it plays (tap it to jump), its length and a speed button (1x, 1.5x, 2x); only one plays
  at a time. Its length and loudness picture (up to 64 numbers) are kept with it (`chat_attachment.duration_ms`, `waveform`) and it is served inline as audio. Up to 10 minutes, within the 12 MB file limit.
- **Calls.** The phone and video buttons in a conversation's header ring the other person (also from the front page of Messages, and "Call back" on a call's line). The other person
  gets an answer / decline card wherever they are in Orion (and a notification when the tab is hidden), with "Sound only" for a video call; a call nobody answers in 40 seconds is missed,
  and one to someone who is not online or already on a call is recorded as missed and the caller is told why. A call runs full screen or as a small pill (keep working), with mute,
  camera on and off (a sound call can turn its camera on), screen sharing (the other side sees the screen big and the camera small), "is muted" and "weak connection" notes and, in a
  sound call, a ring around the other person that follows their voice. When it ends each conversation gets one line ("Video call · 12:03", "Missed voice call", "Cancelled", "declined") that cannot be edited,
  deleted or forwarded. Sound and picture go straight between the two browsers (WebRTC, encrypted) and are never recorded or stored; only who, which kind, how it ended and how long are kept.
  One call at a time per person. The microphone and camera need the secure (https) address of Orion (Tailscale's, or localhost); on the plain address a call or voice note says so.
- **Details.** The panel beside a conversation shows the person, the muted / kept-at-top / archive choices, shared photos, files and pinned
  messages.

**Where.**
- ui: groups are `components/messages/` `GroupAvatar`, `NewGroupDialog`, `GroupSection` (the people and name in the details drawer) and `SystemLine`; `components/calls/` (`CallHost` (lazy, mounted once in `Layout` for signed-in people), `useCallEngine` (the whole call: ringing, the connection, microphone, camera, screen, ending), `CallScreen`, `ringtone`, `startCall`: any page asks for a call with the window event `orion-call-start`),
  `components/messages/` also holds `CallLine`, `VoiceNote` and `RecorderBar`; `pages/MessagesPage.tsx` (the lists, drafts, which conversation is open), `components/messages/` (`ConversationList`, `ThreadView`,
  `ThreadHeader`, `MessageList`, `MessageBubble`, `MessageMenu`, `Composer`, `ThreadPanels` (search, details, forward, viewer), `useThread`
  (one conversation's messages and everything that happens to them), `format.ts`), `context/ChatContext.tsx` (the socket, unread, presence,
  typing, subscriptions), `components/EmojiPicker.tsx`
- api: `routers/messages_router.py` (REST and the `/api/messages/ws` WebSocket; `/messages/calls/config` and `/messages/calls/ringing`), `chat.py` (all the rules), `chat_media.py` (files),
  `chat_ai.py` (AI help), `chat_groups.py` (the group rules: making one, who is in it and who runs it; the only writer of `chat_member`), `calls.py` (the call switchboard: ringing, who answered, passing the connection set-up between the two browsers, writing the call line; the only writer of `chat_call`)
- tables: `orion_ods.direct_chat`, `chat_message` (with `reply_to_id`, `edited_timestamp`, `deleted_timestamp`, `forwarded`, `client_id`),
  `chat_read`, `chat_attachment` (with `duration_ms`, `waveform`), `chat_reaction`, `chat_pin`, `chat_member_setting`, `chat_call` (and `chat_message.call_id`), `chat_member` (the people of a group; `direct_chat.kind`, `title`, `created_by`; `chat_message.system`); files in `data/chat-media/`. The base tables are in
  `schema.sql`; everything added since is in `migrate_chat.sql`.

**Rules.**
- Any signed-in user can message any other or make a group, and only the people in a conversation can read or change anything in it: every route and
  every socket event checks membership from the database (for a group, from `chat_member`, on every call, so a person who has left or been removed reads nothing more at once), never from an id sent by the browser. Only a message's sender can edit or
  delete it. A file is served only to the two members and as the type it was checked to be (`nosniff`; images and video inline, everything
  else as a download).
- Sending, editing, reacting, searching and typing are rate-limited per person (40 messages a minute, 30 edits, 60 reactions, 20 searches
  per 30 seconds, typing 6 per 10 seconds); a client over the limit is slowed, not disconnected.
- Message text is only ever rendered as text. The WebSocket authenticates with the same session cookie. Prod needs `uvicorn[standard]`
  for WebSocket support.
- Messages are not end-to-end encrypted; the server can read them, as it can any other data in Orion.
- A call can be started only between the two members of a conversation, checked from the database; a set-up message (offer, answer, network candidate, a small "state" note of microphone,
  camera and screen) is passed only between the two people of a call that is live, only of those kinds, up to 16 KB and 200 per 10 seconds; 6 calls a minute per person. Ringing and live calls
  live in the application's process (one process on one computer): a restart ends them, and a person whose last browser closes ends their call (a call that was ringing for them keeps ringing, in case it was a reload).
  Which servers the browsers use to find each other is chosen only in `.env` (`ORION_CALL_STUN_URLS`, and `ORION_CALL_TURN_*` for a relay), never by the browser; none is needed over Tailscale or on one network.
  The `Permissions-Policy` header allows the camera, microphone and screen capture for Orion's own pages only.
- Not built: last seen, delivered (as opposed to read) receipts, group calls, a group's own picture, who has read a message in a group, hiding earlier history from a new member, link previews, GIFs and stickers, and virtualised scrolling (history is paged instead).

---

## Raise a request

**Does.** A user sends a support request with optional attachments from the rail or the account menu.

**Where.** ui: `components/RaiseRequestModal.tsx`. api: `routers/support_router.py`, `mail.py`.
Each request is saved under `data/support/` and emailed to `ORION_SUPPORT_EMAIL` (or `ORION_SMTP_FROM`).

---

## Home page

**Does.** The public landing page of the company, shown at `/` to everyone, signed in or not.

**Where.** ui: `pages/HomePage.tsx`, images in `frontend/public/images/`. No API.

---

## Appearance and themes

**Does.** Lets each person choose how the whole application looks and keeps it for them: one of six classic themes (Default,
Midnight, Aurora, Obsidian, Ivory, Flux), light, dark or the device's setting, an accent colour, a visual style, corner
radius, density, interface size, higher contrast and reduced motion. Changes show at once everywhere. It is Settings >
Appearance (`/settings?tab=appearance`), with a quick menu (the palette button in the top bar) for switching theme and mode.

**Two interfaces.** The same application, drawn two ways, chosen in Settings > Appearance > Interface (and by "Try the new look" in the classic top bar,
"Switch to the classic look" in Lumen's account menu, or the command palette). Both show the same pages, data, permissions and actions; nothing about what a
person can do depends on the choice, and it is saved per person like the rest of the appearance (`experience`: `classic` or `lumen`).
- **Classic** is the original: the dark navigation rail, dense tables and the six themes above.
- **Lumen** is the new one: a floating **sidebar** (an icon and its name for every area, grouped, one hue per area; "Fold sidebar" at the bottom folds it to a slim column of centred icons with their names as tooltips, and the page beside it moves with it; it never opens or closes by itself, and the choice is kept on the device), a rounded
  top bar with a **search pill** (the command palette: jump anywhere or ask the Copilot), a **+ menu** to start a task, bill, letter, upload or register (only what
  the person may start), the bells, and the account menu. On a phone the dock becomes a floating tab bar (Today, Tasks, search, Messages, All spaces).
  **All spaces** is a searchable grid of every area. **Today** (`/` when signed in) is the front door: a greeting, the person's own numbers (due today, overdue, to
  review, and what clients owe where they may see it), a **My day** list to tick off in place, the tasks that need them, and every space as a tile. The company's own
  page is still what a signed-out visitor sees. Lumen has three palettes (Violet, Ocean, Sunrise; each light or dark), a very round soft style, its own typefaces
  (Bricolage Grotesque for headings, Manrope for text), drifting colour behind the page, a light that follows the pointer over cards, tabs drawn as a pill track, cards
  that rise in, and a small burst of confetti when a task is finished, a review approved or a to-do ticked. All motion stops for "reduced motion" and for devices that ask for less.
- **Inside the pages too.** Lumen is not only a new frame: the shared pieces every screen is built from have a Lumen form, chosen with `useLumen()`, so the whole application changes together.
  - *Tables* (`ui/DataTable`): airy rows on a soft sheet with a glass header; codes (`CS-0004`) as chips, numbers right-aligned in tabular figures, dates quiet, and a column that holds a short
    list of words (a status, a type, a city) as coloured pills (a well-known status keeps its meaning: green, coral, amber; any other word keeps one colour everywhere: `lumen/cells.tsx`,
    checked by `npm run check:lumen`). The text and the filters of every column are unchanged.
  - *The catalog* of the data workbenches (`data/WorkbenchCatalog` -> `lumen/LumenCatalog`): an explorer with a search box over every group, groups with a coloured badge and a count that fold away,
    rows that glow when chosen, and arrow keys. On a phone it is a solid drawer.
  - *Data entry* (`EntityForm`, `OperationalDataPage`): the same fields gathered into sections (Details, Amounts, Dates, Notes), a bar showing how many required fields are filled, a short list of fixed
    choices as tap-able pills instead of a drop-down, quick dates (Today, Yesterday, Start of month), an Add / Edit / Upload switch in the header, a footer that says how many changes are waiting, the
    review of changes as old -> new chips, a drop zone for Excel files, the record history as a timeline, and a warning with an illustration before live records are changed.
  - *Dashboards*: each headline figure sits on a pool of the colour of its tone, counts up when it arrives and is set in the display face; sparklines take the card's colour; bars are rounder; chapters
    and the dashboard title have a mark of the accent; the views are a pill track; tooltips are frosted glass.
  - *Elsewhere*: file and folder icons in the Document Center are coloured tiles by kind (PDF, sheet, picture, folder, client, case); the Data landing page is two gradient portal cards; empty states
    float; every page title is a gradient; tabs everywhere are pill tracks. Everything else takes the look from the shared tokens and classes.
- **The money screens** have their own Lumen layouts over the same data, permissions and actions (the Classic ones are unchanged):
  - *Bill editor*: a bar of numbered steps (Case, Details, Lines, Charges, Extras) that tick as each is complete, one card per step, each line as its own card with move up/down, a totals card that stays in view with the grand total and the checklist
    (case, party name, lines add up, reason given), and the live bill on a paper desk that fits to the width ("Fit" / "Full size"). Saving, the checks and the idempotency key are the same code.
  - *Bill view*: a header with the number, status, who and where, and a ring of how much has been collected (received, held back, credited, still to receive); the bill itself in the middle with its versions, and the GST,
    payments, credit note, letterhead, filing, Drive and typeface panels in a side column.
  - *Outstanding*: the total owed over one bar split by age, then a card per client (search, "over 30 / 60 / 90 days", sort by most owed, oldest or not reminded lately) with its own ageing bar, its bills when opened,
    and the Statement and Remind actions. TDS, GST and Credit notes open with figures on pools of colour; GST also shows the month by month bars above its table.
  - *Bank*: Overview opens on the balance on the accent with the month-end balances as a line behind it, each account's balance and whether the books agree with the bank; the Ledger is a feed grouped by day
    (with the day's money in and out) and the running balance on each line; Reconcile sets what the bank says against what the book says with the gap between them, and each statement line has an in/out arrow; Payables is a queue of
    expenses (a calendar leaf of the day to pay by, tinted by how late, a bar of how much is paid, what is left, Pay and Payments); Payroll is a card per month with a bar of what has gone out, and the pay runs as a list.
- Switching is instant. Moving to Lumen keeps the classic choices (theme, accent, style…) on this device and moving back restores them as they were. A theme belongs to
  one interface (`ThemeDef.experience`); the theme lists show only the current interface's themes, and a saved mix that does not match falls back to that interface's own default.

**Where.**
- Lumen: `frontend/src/lumen.css` (everything is under `html[data-experience='lumen']`), `components/lumen/` (`LumenDock`, `LumenTopBar` with the + menu and account menu,
  `LumenMobileBar`, `LumenLauncher`), `pages/LumenHome.tsx` and `pages/HomeSwitch.tsx`, `lumen/` (`useLumenPointer`, `useCountUp`, `celebrate`), `components/nav/navigation.ts`
  (the one list of areas, shared by both shells, with each area's hue and blurb), `components/appearance/ExperienceSwitch.tsx`, and the interface choice in `AppearanceContext` (`setExperience`)
- the money screens' Lumen forms: `components/billing/lumenBill.tsx` (steps, line cards, paper desk, collection ring, bill header), `components/billing/LumenReceivables.tsx`, `components/billing/StatTile.tsx` (the figure tile of Outstanding, TDS, GST and Credit notes, both looks), `components/bank/BalanceHero.tsx` and `components/bank/lumenBank.tsx` (payable, month and pay-run rows, the balance scale, the direction tile)
- the engine: `frontend/src/theme/` (`themes.ts` the themes and styles as data, `engine.ts` turns them into CSS variables,
  `color.ts` the colour maths, `preferences.ts` what is saved and how it is checked, `apply.ts` puts it on the page and
  caches it, `types.ts`)
- state: `context/AppearanceContext.tsx` (`useAppearance`), with `context/ThemeContext.tsx` kept as the small
  light/dark interface older code uses
- the tokens: `index.css` (section 1 is the Default theme as variables, section 2 maps them to Tailwind names)
- ui: `components/appearance/` (`AppearanceSettings.tsx`, `ThemePreview.tsx`, `AppearanceMenu.tsx`), `pages/SettingsPage.tsx`;
  shared pieces in `components/ui/` (`Toast`, `Tooltip`, `EmptyState`, `Switch` in `Field`), `hooks/usePresence.ts`,
  `hooks/useDialog.ts`
- api: `appearance.py` (checks what is stored), `PATCH /api/auth/me` with `appearance`
- sql: `.cursor/db/schema.sql` and `ensure_user_profile_columns` in `auth.py`: `orion_ods.app_user.appearance` (JSON text)
- checks: `frontend/scripts/check-themes.mjs` (`npm run check:themes`, also run by `pytest` through `test_appearance.py`)

**Rules.**
- **Nothing in the interface has a colour, radius, shadow or duration of its own.** Components use the Tailwind names
  (`bg-surface`, `text-accent`, `bg-primary`, `rounded-lg`, `shadow-raised`) or the classes in `index.css` (`.panel`,
  `.btn-primary`, `.overlay`, `.t-h1` ...). A theme changes the variables behind them. The printed bill, the letterhead
  and the letter editor are paper and keep their own fixed colours.
- **A theme is data.** A theme gives a few seed colours per mode, an accent, a second accent, a secondary hue, fonts, a
  default style and a motion character; `engine.derivePalette` and `deriveAccent` work out the rest (borders, hover, tints,
  status colours, the label on the accent) and push every text colour to WCAG AA. Adding a sixth theme is adding one
  object to `THEMES`.
- **Default is the interface as it was** (with the faint grey and the warning amber nudged to reach 4.5:1). Its values are
  written out exactly (`exact`) and `check-themes.mjs` fails if they differ from the `:root` and `.dark` blocks in
  `index.css`, which is what the page shows before any script runs.
- **A person's choices are layered on the theme**: accent, style, radius, gradients and the background glow are
  `null` until chosen, which means "the theme's own". Mode, density, size, contrast and motion are kept when the theme
  changes. "Reset to theme defaults" clears the overrides; "Undo" steps back through the last twelve changes.
- **Saving is automatic.** Every change is applied, kept on this device (`orion-appearance` in local storage) and, 800 ms
  after the last change, sent to the account. The account's settings are applied when someone signs in (they win over
  the device's); if the account has none, the device's become the account's. The status line says where the settings
  are saved.
- **No flash.** After each change the resolved variables for both modes are cached (`orion-appearance-cache`); the script
  `public/theme-boot.js` (an external file, because the page's Content-Security-Policy refuses inline scripts) replays them before the first paint, choosing light or dark from the device when the mode is System.
- **Contrast is guaranteed by the engine, not by hand.** Body text on the page is at least 7:1, secondary and faint text
  4.5:1 on the page, the card and tinted panels, the accent as text and the status colours 4.5:1 on the surface and on
  their own tint, the label on a primary button 4.5:1, whatever custom accent a person picks. A custom accent is moved
  (lightness only) until it passes.
- **Motion** is tokens (`--orion-dur-*`, `--orion-ease`). "Reduce motion" sets them to 0 and `data-motion="reduced"`;
  the device's `prefers-reduced-motion` is always honoured too. Switching theme or mode cross-fades with the View
  Transitions API where it exists (cut short after 700 ms so the page never waits on it) and eases colours elsewhere.
- Dialogs, drawers, menus and toasts play an exit animation (`usePresence`); dialogs and drawers keep keyboard focus inside
  and return it (`useDialog`).
- Density scales Tailwind's spacing unit (`--spacing`); interface size scales the root font size; radius scales every
  `rounded-*` except pills (`--orion-radius-scale`).
- Chart series are variables too (`--orion-s-*`); only the first follows the accent.
- What the server stores (`appearance.clean_appearance`) is a short list of known keys with checked values (names, a hex
  colour, numbers in range, three or four choices), at most 1 KB. A theme or style name it does not know is kept, so an
  older or newer browser still works; the browser falls back to Default.

**Depends on.** Sign-in (to keep it on the account). Works without it (sign-in page) from the device's copy.
**Used by.** Every screen.

---

## Shell and navigation

**Does.** The navigation rail, top bar, appearance menu, refresh, account menu.

**Where.** ui: `components/Layout.tsx`, `components/WorkspacePanes.tsx`, `workspaceRoutes.tsx`,
`context/TabMemoryContext.tsx`, `components/appearance/AppearanceMenu.tsx`, `components/ThemeToggle.tsx` (the plain light/dark
switch on the sign-in page), `components/RefreshButton.tsx`, `index.css`. Colours, radii and motion: see "Appearance and themes".

**Rules.**
- A rail item is visible only if its `visible(user)` check passes; the checks mirror the server permissions.
- The rail's **Utilities** group holds the everyday tools: Billing (`/utility`), Letterhead (`/letterhead`), PDF tools (`/pdf-tools`, shown to
  the same people as Letterhead) and Documents (`/documents`).
  A new tool is one more item in that group, with its own workspace, routes and access flags.
- `/dashboard` and `/data` are chooser pages kept for redirects; the rail links past them.
- Workspaces stay mounted once visited (see architecture.md).
- The top bar holds the Copilot button; the Copilot panel sits beside the workspace and the command palette (`Ctrl+K`) is mounted here (see "AI Copilot").
- **The app starts small; pages arrive when they are opened.** Opening Orion downloads the shell, the home page, sign-in and React: about
  500 kB (150 kB gzipped), where it used to be 1.6 MB (440 kB gzipped) of every page and the chart library. Every page in
  `workspaceRoutes.tsx` (and Settings and the reset page in `App.tsx`) is made with `lazyPage(() => import('./pages/X'), 'X')`
  (`lazyPage.tsx`): a page is its own file, fetched the first time someone opens it, with its own boundary, so a workspace's tabs and
  the rail stay put and "Loading…" shows where the page will be. The chart library is 445 kB and is fetched by the first dashboard
  (or the first Copilot answer that holds a chart: `assistant/ChartBlock.tsx` is lazy for that reason). `vite.config.ts` puts the
  libraries that rarely change in their own files (`vendor-react`, `vendor-router`, `vendor-charts`) so a release that
  changes only a page leaves them in the browser's cache. The icon library is not forced into a file of its own: each page keeps the icons it
  uses, so the start-up download is only the icons the shell draws (592 kB of the 650 kB budget).
- **A tab left open across a release** cannot fetch a page it has not opened yet (the old file is gone). `ChunkBoundary` shows
  "Orion was updated ... Reload" in the page's place, keeping the rail and the other panes; nothing saved is lost.
- **How the server serves it** (`frontend_serving.py`): files in `assets/` carry a content hash in their name, so they are cached
  for a year (`immutable`); `index.html` and the other top-level files are `no-cache` (revalidated every time), so a release is seen at
  once; a file that is gone is a 404, never `index.html` in its place. Responses over 1 KB are gzipped (`GZipMiddleware`: the app's scripts
  go to about a third; the Copilot's event stream and images are left alone).
- **A budget keeps it that way.** `npm run check:bundle` (after the build; run by CI) fails if the start-up files are over 650 kB or
  include the chart library or any page, or if a page stops being its own file. One eager `import` of a page, or of `recharts`, from
  the shell is enough to bring it all back, and this is what notices.

---

## The database connection pool

**Does.** Lends out open PostgreSQL connections instead of opening one per query. Opening costs about 100 ms here (TCP, password check,
session set-up), so a page that made ten queries spent a second connecting, and eight people at once made each other four times slower.
Measured on the dev PC with real API calls: `auth/me` 216 ms -> 4 ms, billing list 280 -> 14, entity preview 322 -> 5, dashboard
overview 442 -> 161; with 8 callers at once `auth/me` 1,240 -> 11 and the billing list 1,653 -> 85. The database-backed test suites
went from about 215 s to 28 s.

**Where.** `db_pool.py` (the pool: no psycopg2 in it, tested with fakes), `database.py` (`db_cursor`, `get_connection`, `raw_connection`,
`pool_stats`, `warm_pool`, `close_pool`), the 503 handler and warm/close calls in `main.py`, `health.py` and the System tab.

**Rules.**
- **Callers are unchanged.** `with db_cursor(commit=True) as cur:` commits on success and rolls back on an error; without `commit` nothing is
  saved. `conn = get_connection()` ... `conn.commit()` / `conn.rollback()` ... `conn.close()` (billing, the warehouse and Tally loaders) now
  means "give it back": `close()` rolls back anything left open and the connection goes to the next borrower.
- **A connection is clean when lent.** Nothing in Orion sets session state (no `SET`, advisory locks, temp tables, `LISTEN`, autocommit), so
  the whole reset is a rollback: an unfinished write and its row locks are gone before anyone else gets the connection. Do not introduce
  session state on a pooled connection; if something truly needs it, use `raw_connection()` and close it yourself.
- **A dead one is not lent.** Closed, older than 30 minutes (`max_age`), or idle over 30 s and no longer answering `SELECT 1` (the database
  was restarted): it is thrown away and replaced, so a restart of PostgreSQL heals itself on the next request.
- **A hard limit.** `ORION_DB_POOL_MAX` (20; never above 100, PostgreSQL's own limit). When all are busy a caller waits up to
  `ORION_DB_POOL_TIMEOUT` (15 s), then the request is answered **503 "The server is busy"** with `Retry-After`, not a 500. Dev and prod each
  have a pool in one PostgreSQL that allows 100 connections, so keep each well under 50. Idle connections beyond two close after 5 minutes.
- **Do not hold a connection across slow work** (a call to Tally or to an AI provider, a sleep): borrow, query, give back. A borrower that
  forgets to close is caught when it is garbage collected and logged ("dropped without being closed").
- **The pool is made on first use**, with two connections opened at start (`warm_pool`), and per process (a forked child never closes its
  parent's connections: they share sockets). The System tab shows how many are busy of the maximum, and says so when requests gave up
  waiting. Tests: `test_db_pool.py` (fakes, always), with `ORION_DB_TESTS=1` against the dev database (unfinished writes invisible, row locks
  released, a connection killed on the server replaced, 30 threads on 5 connections).

## Logs, health and the System page

**Does.** Lets someone find out what the server is doing, and what went wrong, without asking the person at the office PC to look.

**Where.**
- api: `observability.py` (logging, request ids, the access line, the error boundary, the in-memory problem and slow-request
  lists), `health.py` (the answers), `routers/health_router.py`; `/api/health` and `/api/health/ready` are in `main.py`
- ui: the **System** tab of Admin (`components/admin/SystemHealthPanel.tsx`)
- files: `data/logs/orion.log` (10 MB, 10 files kept; git-ignores `data/`)

**Rules.**
- **Every request has a reference** (the browser's `X-Request-ID` if it is a plain token of 8 to 64 characters, else a fresh 16
  hex digits). It is on every log line made while serving the request, in the `X-Request-ID` response header, and in the message
  of an unhandled error, so "reference 3f9a..." finds the exact lines and the traceback. Log format:
  `time LEVEL [reference uUSERID] logger: message`. The user is a number, set by `get_current_user` (`bind_user`).
- **One access line per request**: method, path, status, milliseconds. Never the query string (a password-reset link carries its
  token there), never a body or a cookie. Health checks, assets and images are logged at DEBUG. A request slower than
  `ORION_SLOW_REQUEST_MS` (2000) is a warning and is kept for the System page; a 5xx is an error.
- **An unhandled error** is caught once, logged with its traceback (`orion.errors`) and answered with a 500 JSON message that names
  the reference and nothing about the cause, still carrying the CORS and security headers.
- **Where it goes**: the console and the rotating file; `ORION_LOG_LEVEL` (INFO), `ORION_LOG_DIR`, `ORION_LOG_FILE=0`,
  `ORION_ACCESS_LOG=0`. A background thread that dies is logged (`threading.excepthook`). Library chatter (httpx, botocore, PIL)
  is held at WARNING. uvicorn's own access log is turned off, because ours replaces it.
- **Nothing fails silently.** An `except Exception` either re-raises or logs. A condition that is normal on a machine (not owning a
  table that already exists) is logged at DEBUG, never as a warning: the System page says "needs attention" for any error in the
  last hour, and a false alarm that is always there teaches people to ignore it. `test_observability.py` keeps `print` out of the
  backend and checks that the handlers that used to hide a failure now say so.
- **Four health answers.** `/api/health`: the process is up (unchanged: the desktop launchers poll it). `/api/health/ready`: it
  can reach the database and the schema is right, 503 when not (`{"status":"degraded","database":"ok","schema":"problem"}` when only
  the schema is wrong; the healthy body is unchanged), public, and answered from a result at most 5 seconds old.
  `/api/health/version`: the commit this process started on, plus the ref, the previous commit and the time from `data/release.json`
  (public; a deploy's smoke test asks it). `/api/health/details`
  (administrators): the database's round trip, when each warehouse load and the backup last worked (read from `etl_run` and
  `backup_run`, not reported by the jobs), request counters since start, the slowest recent requests and the last warnings and
  errors, and a plain list of what needs attention (database silent, backup overdue or blocked, a load that failed since it last
  worked, errors in the last hour). The System page shows this and refreshes every 30 seconds. The counters and the problem list
  are in memory and reset on restart; the file keeps the history.

## Running and deploying

**Where.** `scripts/` (PowerShell for Windows, `.sh` for macOS), `desktop/`, `deploy/env.prod.example`.

| Script | Purpose |
|---|---|
| `install-windows.ps1`, `install-mac.sh` | One-time setup: tools, virtualenv, `.env`, database, frontend packages |
| `init_db_windows.ps1`, `init_db_mac.sh` | Create or update the database from every `.sql` file. Safe to re-run |
| `start-modern.ps1` / `.sh`, `start-api.*`, `start-frontend.*` | Start dev |
| `start-desktop.ps1` / `.sh`, `install-desktop-app.*` | Dev in a native window |
| `deploy.ps1`, `start-prod.ps1`, `install-prod-desktop-app.ps1` | Prod, on the office PC only |
| `tailscale-serve.ps1` / `.sh` | Expose the dev UI on the tailnet over HTTPS |
| `load-env.ps1`, `windows-common.ps1`, `macos_python_env.sh`, `pip_env.sh`, `tailscale_cmd.sh` | Helpers the others source |

`deploy.ps1` refuses to run unless `.env` has `ORION_ENV=production` and the folder has no local edits.

**Migrations and a deploy that checks itself.**

*Does.* Applies every database schema file in order, records each result, and stops a deploy when one fails. Takes a safety dump of the
production database before anything changes, tests the new server before calling the deploy done, and puts the previous version back
when that test fails.

*Where.* `backend/app/migrate.py` (the runner and `python -m app.migrate`), `.cursor/db/migrate_schema_migrations.sql` (its table),
`entities.SQL_MIGRATIONS` (the list), `backend/app/deploy_tools.py` (`backup`, `smoke`, `release`, `release_info`), `scripts/deploy.ps1`,
`health.py` and `main.py` (the `/api/health/version` and readiness answers), the System tab.

*Rules.*
- **The list is the registry.** A schema file reaches prod only if it is in `entities.SQL_MIGRATIONS`, in both init scripts, and (for a
  warehouse schema) re-run by its `ensure_*`. `test_migrate.py` and `test_contracts.py` fail when these disagree. Legacy files that
  only the init scripts apply (`schema.sql`, `grants.sql`, the early `migrate_app_user_*` ones) are deliberately not in it.
- **Applied when new or changed.** `orion_ods.schema_migrations` keeps the file's checksum (line endings ignored), its status
  (`applied` or `failed`), attempts, duration and the error. An unchanged applied file is skipped. The three warehouse schemas always
  re-run and are recorded. Every file must still be safe to run twice.
- **A failure is recorded and visible.** The runner goes on to the other steps, then reports. In production the API refuses to start
  (`MigrationFailed`); in development it logs and continues, `/api/health/ready` answers 503 and the System tab says "Database
  schema: ...". A row for a file the running code does not know is ignored (a rolled-back release leaves one behind).
- **Ownership.** A step is run as the app role and, if refused for ownership, as the PostgreSQL superuser when
  `ORION_POSTGRES_SUPER_PASSWORD` is set; without it the error says to set it.
- **The deploy's order is a contract.** previous version noted -> checkout -> packages -> safety dump -> production-settings check ->
  `app.migrate` -> frontend built on the side and swapped -> old server stopped, new one started -> smoke test -> release record; any
  failure after the checkout restores the previous version. `test_deploy_tools.py` pins the order, the rollback and the resume.
  The dump and the migration come **before** the old server is stopped, so a failure of either leaves production exactly as it was.
- **The dump** (`pg_dump -F c`, plain, into `C:\orion-backups`, 5 kept) is verified with `pg_restore --list` (all four schemas) and needs
  free disk space; it is not the encrypted off-site backup (`docs/backup.md`), which is separate and unchanged.
- **The smoke test** proves the *new* code answers: liveness, readiness (database and schema), `/api/health/version` equal to the
  expected commit, the web app and its script, the security headers and request id, a public API page. The version is taken from
  git when the process starts, never from the release record, which is written afterwards.
- **A rollback is code only.** Migrations are additive, so the old code runs on the new schema; if data was damaged the dump's path is
  printed. `-Verify` is for the desktop-shortcut routine: it tests the already-running server for this folder's commit and writes the
  record, and changes nothing.

**Checks before code reaches prod.** GitHub Actions (`.github/workflows/ci.yml`) runs the backend tests and `ruff` on Windows, the frontend `oxlint`, type-check,
build, bundle-size (`npm run check:bundle`), bill-arithmetic (`npm run check:bill`) and theme checks, and `pip-audit`/`npm audit` on every
pull request. **The linters look for bugs, not style** (`ruff.toml`; `frontend/.oxlintrc.json`): unused or undefined names, a repeated
dictionary key, a `raise` outside a handler, an error swallowed with no stated reason, a React hook called after an early return or with
a missing dependency, an ARIA role without its required state. When they were first run they found real faults (a hook called after an
early return in two pages, which React forbids because the hook order changes when the page's permission or loading state does; the calculator's thousands-comma rule and a test that
never matched because `\b` had become a raw backspace character; a bare `raise` that would have crashed instead of reporting the real
database error; a doubled dictionary key). Formatting is **not** enforced (it would rewrite most files); `.editorconfig` and
`.pre-commit-config.yaml` (optional) are there for editors and for checks on commit. Python packages are pinned (`backend/requirements.txt` plus the
full lock `backend/constraints.txt`), and Dependabot proposes updates. `deploy.ps1` installs from the lock and runs
`python -m app.startup_checks` before stopping the running server. With `ORION_ENV=production` the API (`app/startup_checks.py`, called first
in `lifespan`) refuses to start while the session secret (under 32 characters) or the database password is empty or a development/example
value, and `ensure_default_admin` refuses to create the first administrator with a default or short (under 12 characters) password. In
development nothing is enforced; a warning is logged when the session secret is the published one. Tests: `test_startup_checks.py`,
`test_supply_chain.py`.

**Downloads in the native window.** `desktop/app.py` and `desktop/prod_app.py` set
`webview.settings["ALLOW_DOWNLOADS"] = True`. Without it pywebview cancels every download without a message, so
Excel exports, upload templates and bill PDFs save nothing. With it, a download opens a Save As dialog that starts
in the Downloads folder. In a normal browser the file goes to the browser's own download folder.
