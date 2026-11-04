# Change impact: what else moves when you change something

Orion declares many things in one file and relies on them in another. This page lists those links, so a change
in one place is carried through to every place that depends on it.

How to use it: find the thing you are about to change in **The links**, follow every row, then use the matching
**recipe**. The last column says whether a test catches a miss. "No" means only you will.

Tests referred to here are in `backend/tests/test_contracts.py`. They read source files and need no database.

---

## The links

### A column in an `orion_ods` business table

One column is named in up to seven places. They are not generated from each other.

| Declared in | Relied on by | Effect of a mismatch | Caught by a test |
|---|---|---|---|
| `.cursor/db/schema.sql` (new databases) **and** an `ADD COLUMN IF NOT EXISTS` in a file applied at startup (existing databases) | everything below | Works on a fresh database, fails on prod, or the reverse | No |
| `form_fields` in `backend/app/entities.py` | the generic form, the change preview, the Excel template, the Excel upload | See the next section | Yes: every field must be a column |
| `MERGE_KEYS` and `MERGE_FALLBACK` in `entities.py` | Excel upload matching (`db_utils.upsert_many`) | Uploads duplicate rows or overwrite the wrong one. A key that is not unique makes uploads fail with "N records match"; a key that is too wide makes every upload an insert | Yes: every key must be a column |
| the entity's spec in `backend/app/dw_sync.py` (`attrs`, and for facts also `dw_cols` and `compare`) | the warehouse load | Load fails, or the column silently never reaches the warehouse | Yes for a named column that does not exist. **No** for a column you forgot to add |
| `.cursor/db/dw_schema.sql` (in `CREATE TABLE` and as `ADD COLUMN IF NOT EXISTS`) | the warehouse load | Load fails with "column does not exist" | Yes |
| SQL in `backend/app/dashboard/` (`filters.py` scopes, `engine.py`, `views*.py`, `records.py`) | Orion dashboards, which read `orion_dw` | A dashboard errors or shows wrong totals | No. A test does check nothing in that folder reads `orion_ods` |
| `.cursor/db/data-model.md` | people and AI reading it | Wrong mental model | No |

Every one of these tables also has `created_by` and `last_updated_by` (`migrate_audit.sql`), and every warehouse
table `source_created_by`, `source_last_updated_by` and `expired_by`. They are not in `form_fields`. The write
helpers in `db_utils.py` set them from the user the route passes in, and `billing.py` sets them on the revenue
entries it writes. A new write path that skips the user leaves history showing no name; a test checks the
existing ones.

The record browser (preview and export) is the one consumer that needs nothing: it selects every column of
the table, so a new column appears there on its own. It hides columns whose name contains `timestamp`.

### What `form_fields` drives

An entry in `form_fields` is not just the form. Changing a field's key, `type`, `options`, `required`,
`readonly`, `source_table` or `compute_from` changes all of these at once:

| Consumer | File | What it takes from the field |
|---|---|---|
| The create and edit form | `frontend/src/components/EntityForm.tsx` | which input to draw, options, lookups, computed and read-only behaviour, `hint` |
| "What will change" preview and the payload sent | `frontend/src/formPayload.ts` | which fields are sent; `readonly` fields are never sent |
| Server-side cleaning | `backend/app/payload.py` | type coercion, `required`, computed fields; `readonly` fields are dropped |
| Excel template | `backend/app/excel_import.py` (`build_template`) | one column per field that is not `readonly`, with a note built from the type |
| Excel upload | `excel_import.py` (`parse_workbook`) | accepted headers (key, label, camelCase), lookups by name or code, coercion |
| Lookup dropdowns | `entities_router.py` `/field-options/` | `source_table`, `source_display_column`, `source_pk_column`, `source_from` |
| Record picker label | `entities_router.py` `/options` | the entity's `option_label`, `option_from`, `option_pk` |

So: **adding a field changes the Excel template.** A spreadsheet made from an older template still uploads;
the new field is simply not set. The upload recognises a column by the field's key, its label, or the key in
camelCase or with spaces. A header it does not recognise is **ignored without an error**, so renaming a
field's key and label makes old spreadsheets upload with that column silently dropped. Marking a field
`readonly` removes it from the form's payload, the template and the upload.

Derived values are computed twice and must agree: `apply_computed_fields` in `backend/app/payload.py` and the
`compute_from` / `compute_op` handling in `EntityForm.tsx` (`amount_after_tax_gst`, `driven_km`, `month_year`).

### Which entities exist

| Declared in | Relied on by | Caught by a test |
|---|---|---|
| `ENTITIES` in `entities.py` | the API, forms, Excel | |
| `DATASET_GROUPS` in `frontend/src/pages/OperationalDataPage.tsx` | the catalog on the left of Operational Data. An entity missing here cannot be opened | Yes: the two lists must be equal |
| `DIMS` / `FACTS` and `REFRESH_ORDER` in `dw_sync.py` | the warehouse | Yes: every entity table must have a load |
| other entities' `source_table` / `source_display_column` | their dropdowns | Yes for the table and key column; **No** for the display column |

### A dropdown's allowed values

`options` in `form_fields` and a `CHECK` constraint in `schema.sql` usually both list the values. Adding a value
to one and not the other gives a form that offers something the database rejects. Not caught by a test, except
for the one below.

`transaction_status` (`Committed`, `Prospective`, `Cancelled`) is the important one. It is also hard-coded in
`dashboard/filters.py` (`STATUS_ORDER`), `dashboard/measures.py`, `billing.py` and
`frontend/src/components/billing/BillPayments.tsx`. Treat the three values as fixed. A test checks the form
options against `STATUS_ORDER`.

### `orion_ods.case_transaction` (revenue)

Three features share this table.

| Who | What it does with it |
|---|---|
| Operational Data, "Transaction" | creates and edits rows that have no `bill_code`, but never a `Committed` one: a trigger refuses it (money with no bill is a Bank `other_receipt` entry) |
| Billing | owns every row that has a `bill_code` (see features.md) |
| Orion dashboards | read it from `orion_dw.fact_case_transaction`: cash collected is the `Committed` entries by `received_date`, and what is owed comes from the bills less those entries |
| Orion warehouse | `fact_case_transaction`, with `bill_sk` pointing at `fact_bill` |

The trigger `case_transaction_committed_needs_bill` (`migrate_data_rules.sql`) fires on insert and update: a new code path that writes this
table as `Committed` with no `bill_code` fails with `check_violation`, so such money goes through `billing.py` or a Bank entry. It also means
`entities.invalid_reason`, `CONSTRAINT_MESSAGES` and the trigger say the same thing.

Consequences: changing what a status means, which date a row carries, or which column holds the money changes
dashboard totals for every bill. `received_date` drives the dashboards' cash figures and each bill's "days to collect".

### `orion_ods.employee_transaction` and `salary_run` (salary lines and the pay runs that pay them)

| Who | What it does with it |
|---|---|
| Operational Data, "Employee Transaction" | enters and edits a salary line. **Salary Paid is read-only** (not asked when adding, not an Excel column): a line starts as `No` (the database sets it when it is left out or empty) and becomes `Yes` only through a pay run, and a line in a pay run is read-only |
| `payroll.py` (Bank > Payroll) | the only writer of `salary_run`, and the only thing that sets a line paid (`salary_paid` Yes with its `salary_run_id`) or takes it back |
| The view `bank_movement` | one `payroll` movement per pay run that is not reversed: what its lines came to, on the run's day, from its account |
| The view `bank_expected` | `payroll_due`: each month's lines with no run, at the month's last day |
| `bank_match` | a statement line can match a pay run (`source = 'payroll'`, `source_ref` the run number); `bank.py` `_EXCEPTION_SQL` joins the run, so a reversed run shows on Reconcile as "matched, then changed" |
| The dashboards | "salary pending" and the Payroll measures read `salary_paid` through the warehouse, which follows the lines as before |

Consequences: the trigger `salary_line_follows_its_run` refuses a new line marked paid with no run, and a change to a line of a run that stands; a new writer of
`employee_transaction` meets it (`entity_service.CONSTRAINT_MESSAGES`, `entities.locked_reason`). The trigger also turns a missing `salary_paid` into `No` (and the column
is `NOT NULL DEFAULT 'No'`), because Payroll and "salary pending" only find lines that say `No`. Salary loaded from Excel starts as not paid: mark the month paid in Payroll. A new reader that wants "what was paid out as salary" reads `salary_run` (not
reversed) and its lines, never `salary_paid` alone.

### Typing an amount of money (`components/ui/MoneyInput.tsx`)

Every place a person types rupees uses `MoneyInput`: it shows the Indian commas as the amount is typed (1,23,456.50), keeps the cursor after the same digit, and shows the amount in words under
it. The page's state is still the plain number (no commas), so `amountOf`, `billCalc.ts` and every request body are unchanged. The text logic (`billing/moneyText.ts`, `rupeeWords.ts`) has no React
in it and is checked by `npm run check:money` (also in CI). A field in lakh passes `scale={100000}` so its words say the real rupees. `words={false}` is for a field that sits in a table row (a
bill line's rate, a charge) where the line's own total is already shown. A number field of the entity registry (`entities.py`) that is money carries `"money": True`; `EntityForm.tsx` and
`AmountBreakdownBox.tsx` then use `MoneyInput`. A new money field in the registry, or a new amount in a dialog, must do the same.

### Choosing several values (`components/ui/MultiSelect.tsx`)

One component does every "pick several" in the app: the types and cities of a tender search (`pages/tenders/SearchForm.tsx`) and a document's tags (`components/documents/TagPicker.tsx`, in the
upload dialog and the document drawer). The salary lines of a pay run (`PayrollModals.tsx`) and the report's Columns menu (`ReportTable.tsx`) are checklists with the same
"select all / clear" actions. A new place that takes a list of words uses `MultiSelect`, not a comma-separated text box. The limits it shows (`max`) must be the ones the server
enforces: for a tender search `MAX_TYPES`/`MAX_CITIES` in `SearchForm.tsx` and `tenders.MAX_TERMS`/`MAX_CITIES`; for tags `options.max_tags`.

### The minimum balance (`bank_account.low_balance_floor`) and the duplicate-expense warning

| If you change | Also change |
|---|---|
| what counts as "below the minimum" or the two-week look-ahead (`bank.alerts`, `LOW_BALANCE_DAYS`) | the Overview banner (`BankOverviewPage.tsx`), the Copilot insight (`ai/insights._bank`) and `get_bank_balance` (`minimum_balance_alerts`): all three read `bank.alerts()`, never their own sums. `forecast()` is of all accounts together, so the projection alert compares the combined balance with the combined minimums |
| `bank.save_account` or the account form | a minimum that is left out of the request keeps its value and one sent empty is cleared (`exclude_unset` in `bank_router`), so a client that does not know the field never wipes it |
| what looks like a duplicate expense (`entities.find_possible_duplicates`) | the form's review step, the upload result (`_upload_warnings`) and the Copilot confirmation (`_prepare_create`) use the same function; a kind of record opts in with `duplicate_check` on its entity |

### `orion_ods.credit_note` and `bill.credited_*` (what credit notes took off a bill)

| Who | What it does with it |
|---|---|
| `credit_notes.py` | the only writer of `credit_note` and `credit_note_counter`: make, approve, refuse, withdraw, reverse; the rights (`can_approve`) are decided here and sent to the screen |
| `billing.apply_credit` / `unapply_credit` | the only code that, for a note, changes the bill's `credited_*` columns, its open revenue entry (`_sync_revenue`) and its GST (`_sync_gst`); `_sync_revenue` and `_gst_due` read the credited figures, so **a new reader of a bill's amount owed or GST due must subtract them** |
| `receivables.py`, `list_bills` / `BillingPage.tsx`, `card_from`, `payment_status` | balance = grand total - credited - received; a bill settled with a credit note reads Settled |
| `list_bills(client_code, case_code, month, search)` / `BillFilters.tsx`, `client.ts` `bills(...)`, `BillingPage.tsx`, `LumenBillList.tsx` | the filters are exact conditions (never SQL text); a typed month in the search (`month_hint`) is also matched on the client in `LumenBillList` so the two agree; `test_bill_search.py`; callers in `clients.py`/`cases.py` and the Copilot's `list_bills` tool use the same function |
| `BillBar.tsx` / `BillEditorPage.tsx` (`preview`, `blocker`, `save`) | the bar is the only place the editor shows the total, why saving is blocked and the Save button, in both looks; the Preview window draws `BillDocument` through `PaperDesk` from the same `preview` object the page builds, so a new field on the bill goes into that object as well as the form. From 1500px the same `preview` is drawn in a pane beside the form instead (`SIDE_BY_SIDE` in the page and the `min-[1500px]` classes beside it are one figure: change both) |
| The view `bank_expected` (`migrate_bank.sql`) | the GST still to pay on a bill is its GST less `credited_cgst` and `credited_sgst`, less what is paid |
| `gst_position.py`, `GstPage.tsx` | output GST less the GST on approved notes by `note_date`'s month |
| The warehouse and the dashboards | `fact_bill.credited_*` (`dw_sync.py` in `attrs`, `dw_cols` and `compare`, `dw_schema.sql`); `engine.REVENUE`, `BILLED`, `GST`, `filters.BILL_OPEN` and every `b.cgst_amount + b.sgst_amount` in `dashboard/` subtract them (`test_credit_notes.py` fails when a new reader of a bill's GST does not) |
| `sql_guard.OWNED_TABLES` | `credit_note[a-z_]*` changes only through the application |
| The Orion dashboards (`dashboard/engine.py` `COLLECTED`, `SETTLED`, `TDS_HELD`, `CREDITED`, `ITC`; `filters.py` `BILL_OPEN`, `BILL_CASH`, `BILL_TDS`, `PAY_STATUS_SQL`) | cash is the entry less `fact_case_transaction.deducted_amount` (kept on the entry by the trigger `bill_payment_deduction_totals`), what settles a bill and the collection rate are the whole entry, and the credited figures come off revenue, billed, GST and owed. `test_dashboard_money.py` pins them to Billing, Utility > GST and the Bank |

Consequences: the table is owned by the database owner (the migration runs as it), so a cleanup that must delete rows disables the trigger `credit_note_kept` as that owner and
never in production; a credit note's `total` is GST-included and its parts are worked out at approval from what is open then; a bill with an approved note cannot be cancelled;
adding a GST payment beyond the reduced GST is refused by `_sync_gst`.

### `orion_ods.bill_payment_deduction` (what a client held back from a payment: TDS and the like)

| Who | What it does with it |
|---|---|
| `billing.record_payment` / `reverse_payment` (and `clean_deductions`) | the only writer of the rows: a payment's deductions are inserted in the same transaction as the revenue entry, and reversed (never deleted) when the payment is reversed. The entry holds cash + deductions; the bill's entries must still add up to its grand total |
| The view `bank_movement` (`migrate_bank.sql`) | a client receipt is the entry's amount **less** its deductions that are not reversed: the bank sees only the cash. So `migrate_deductions.sql` must run **before** `migrate_bank.sql` (it does, in `SQL_MIGRATIONS` and both init scripts) |
| `tds.py`, `routers/tds_router.py`, `pages/utility/TdsPage.tsx` | read the TDS rows as a ledger; `set_matched` writes only the Form 26AS tick |
| `receivables.py`, the bill card, `payment_status` | read `received` as the **settled** amount (cash + deductions) so a bill paid net of TDS is Paid and leaves Outstanding. `_revenue_summary` adds `deducted`, and per entry `cash` and `deductions` |

Consequences: a new way to take money against a bill must go through `record_payment` (so the deductions and the bank agree); `bank_match` amounts are the cash, so a statement line for a payment with TDS matches the cash; the warehouse (`fact_case_transaction`) does not carry the deduction, so the dashboards' "collected" includes TDS; the deduction trigger `bill_payment_deduction_kept` makes a test or a cleanup that deletes rows disable it first (never in production).

### `orion_ods.expense_transaction` and `expense_payment` (expenses and what is paid on them)

| Who | What it does with it |
|---|---|
| Operational Data, "Expense Transaction" | creates and edits the expense: its status, amounts, **Pay by** day (`due_date`). When a new expense also says it was paid (`create_fields`: Paid On, Paid From, Payment Reference) the same save records the payment through `payables.pay_on_entry`; it never records a payment on an existing one |
| `payables.py` (Bank > Payables) | the only writer of `expense_payment`; reads the expense for what is owed and its ageing |
| The view `bank_movement` | one movement per payment that is not reversed (`source = 'expense'`, `source_ref` = the payment number, the payment's day and account); an expense that is unpaid is **not** a movement |
| The view `bank_expected` | Prospective expenses, and Committed ones for what is still unpaid, on `COALESCE(due_date, transaction_date)` |
| `bank_match` | a statement line matched to an expense is matched to its payment; `bank.py` `_EXCEPTION_SQL` joins the payment, so a reversed payment shows on Reconcile as "matched, then changed" |
| The warehouse | `fact_expense_transaction.due_date`, `vendor_gstin`, `vendor_invoice_no` (`dw_sync.py` in `attrs`, `dw_cols` and `compare`, `dw_schema.sql`); payments are not loaded, and the dashboards still use the transaction date and the pre-GST amount |
| `gst_position.py` (Utility > GST) | reads `expense_transaction.gst`, `vendor_gstin`, `vendor_invoice_no`, `transaction_status`, `transaction_date`, plus `bill` and `bill_gst_payment`. A new way an expense gets GST, or a new status, changes what counts as credit |
| `entities.invalid_reason` (`_itc_problem`) | an expense with GST needs the supplier's GSTIN and invoice number. A new writer of `expense_transaction` that bypasses `entity_service` (as attendance does, with no GST) must meet it itself |

Consequences: the trigger `expense_keeps_its_payments` refuses cancelling an expense, taking it off Committed, or lowering it below what was paid; a new writer of
`expense_transaction` meets it (`entity_service.CONSTRAINT_MESSAGES`, `entities.invalid_reason`). A new reader that wants "what was paid" reads
`expense_payment` (not reversed), never `transaction_date`. The Excel template for Expense Transaction has **Pay By**, and (for people who may change the bank) **Paid On**, **Paid From** and **Payment Reference** columns; tell staff. `option_labels` / `option_aliases` on a field change only what is shown and typed, never what is stored.

### An employee's private details and documents

| If you change | Also change |
|---|---|
| a private column of the Employee (`private_columns` in the entity) | `form_fields`, `field_rules` and `employee_ids.py`, `migrate_employee_documents.sql`, `data-model.md`. Aadhaar and PAN stay **out** of the `dw_sync.py` Employee `attrs` and `dw_schema.sql` (a test fails if they are loaded). Salary is loaded, so it must also be in the spec's `private_columns` and left out of `preview_public`, and `record_history` must keep hiding it from people who cannot change employees |
| a new Excel-visible reader of the employee table | it must read through `entities_router._shown_source`, or someone who can only view operational data will see Aadhaar, PAN and salary |
| the kinds or sizes of file an employee can have | `DOC_TYPES`, `FILE_TYPES` and the limits in `employee_documents.py`; the accepted list is sent to the browser, so the panel follows |
| who can open an employee's documents | `employee_documents_router.py`: every route has `require_ods_write` and a test checks it. A new route needs it too |
| where the files are kept | They are `bytea` in `orion_ods.employee_document` so the encrypted daily backup (`docs/backup.md`) includes them. Moving them to disk means they are no longer backed up |

### Contacts and EMDs (`orion_ods.contact`, `emd`, `emd_document`)

| If you change | Also change |
|---|---|
| a column of `contact` or `emd` | the `ENTITIES` entry (`form_fields`, `field_rules`), `migrate_contacts_emd.sql`, `dw_sync.py` (`DIMS["Contact"]` / `FACTS["EMD"]` and `dw_schema.sql` `dim_contact` / `fact_emd`) if it is warehoused, `data-model.md`, and the record sets in `dashboard/records.py` if a dashboard lists it. A contact's email, phone, address and notes stay **out** of the warehouse on purpose |
| the lists (roles, statuses, methods, modes, EMD statuses) | `entities.py` (`CONTACT_*`, `EMD_*`), the CHECK in `migrate_contacts_emd.sql` (a test compares them), and for an EMD status also `EMD_OPEN` in `dashboard/views_ops.py`, `_EMD_OPEN` in `dashboard/explore.py`, `EMD_ORDER`, and the `emd` scope's `Cancelled` exclusion in `dashboard/filters.py` |
| a rule on a record | `entities.invalid_reason` (the reason shown before the save), the named CHECK, and its message in `entity_service.CONSTRAINT_MESSAGES` |
| the kinds or sizes of file an EMD can have | `DOC_TYPES` in `emd_documents.py`; the file types and limits are `employee_documents.py`'s, so a change there changes both. The panel is `EmployeeDocuments.tsx` with `kind="emd"` (`KINDS`, `DOCUMENT_KINDS`) |
| who can open an EMD's documents | `emd_documents_router.py`: every route has `require_ods` or `require_ods_write` and a test checks it |
| an EMD tile or chart on the Pipeline tab, or a contact tile on Controls | the `emd` / `contact` scopes in `dashboard/filters.py`, `_emd_block` / `_contact_block` in `views_ops.py`, `KPI_HELP`, `MEASURES` and `SNAPSHOT` in `explore.py`, `records.py`, `registry.ts` (`kpiKeys`, `records`), `kpiIcons.tsx`, and the page's `categories('emd_by_status')` / `table('emd')` / `table('follow_ups')` / `table('no_contact')` |
| making an EMD or its refund move the bank | It does not today. A deposit and its refund reach the Bank only as `bank_entry` rows a person records. If this is built, the writer must be one module and a payment must never be recorded twice (see `money-flow.md`) |

### Bills

| If you change | Also change |
|---|---|
| a column of `orion_ods.bill` | `migrate_bill.sql` (the `CREATE TABLE` and an `ADD COLUMN IF NOT EXISTS`), `billing.py` (`_clean_bill`, `MONEY_COLUMNS`, `LIST_COLUMNS`), `BillIn` in `routers/billing_router.py`, `SavedBill` / `BillListRow` in `frontend/src/types.ts`, the editor and view pages, and the Bill spec in `dw_sync.py` plus `fact_bill` in `dw_schema.sql` if it should reach the warehouse |
| how a figure is calculated | `compute_bill` in `billing.py` **and** `calculate` in `frontend/src/billing/billCalc.ts`, the golden vectors in `backend/tests/bill_vectors.json` (both sides must match them: `test_bill_vectors.py` and `npm run check:bill`), and `backend/tests/test_billing.py`, which holds real invoices |
| the default percentages | `DEFAULT_RATES` in both files (a test compares them) |
| how GST is paid on a bill | only `billing.record_gst_payment` / `reverse_gst_payment` write it (and `_sync_gst` keeps the bill's total and flag in step, also after an edit); the screen is `GstPaid.tsx`, the requests are in `client.ts`, the rows are `bill_gst_payment`. The server must keep refusing a request that is not confirmed or whose `seen_paid` is stale. `gst_paid_amount` is also in `fact_bill` (`dw_schema.sql`, the Bill spec in `dw_sync.py`) and the dashboards' GST-owed sums (`engine.py`, `explore.py`, `views.py`, `views_ops.py`, `records.py`). `test_gst_paid.py` |
| what the hover card on a bill number shows | `billing.card_from`, `BillCard` in `types.ts`, `BillCardView.tsx`; `test_bill_card.py` |
| a new place that shows a bill number | draw it with `BillNumber` (a table column: `format: 'bill'` and, on the server, `bill_col`; a record table: name the column `bill_number` / `bill_code`); add it to `test_bill_links.py` |
| a new link that would take someone off the screen they are on | `TabLink` (or `openInNewTab(path)` from code); never `navigate()` for that. In the native window it needs `desktop/orion_windows.py`, so a change to either side needs the other |
| the details a bill can print differently from the template | `PROFILE_BILL_KEYS`, `clean_profile_fields`, `apply_profile_edits` in `billing.py` (and where `_insert_bill` / `update_bill` use them), `profile_fields` in `BillIn`, the `FIELDS` list in `BillOwnDetails.tsx`, `BillProfileEdits` in `types.ts`, `bill.profile_overrides` in `migrate_bill.sql`; add a letterhead field to the template and decide here whether a bill may have its own |
| the letterhead fields | `DEFAULT_PROFILE` in `billing.py`, `BillProfile` in `types.ts`, `BillTemplateModal.tsx`, `BillDocument.tsx` |
| the typefaces and sizes a bill can use | `bill_fonts.py` (`FAMILIES`, `SIZES`) **and** `billing/billFonts.ts` (a test compares them); the PDF reads the same catalogue in `billing_pdf.fonts`. A bill's own choice is `bill.font_family` / `font_size`, the company's is in the billing profile and is left out of the per-bill snapshot (`billing.profile_snapshot`); `bill_fonts.effective` combines them, in `get_bill` and `get_version` |
| a size or width on the printed bill | `BillDocument.tsx` in `em` (never `px`: the base size is the chosen one) **and** `invoice_pdf` in `billing_pdf.py` (multiply by `k = size / 9`, widths by `wide`) |
| a part of the bill that can be left off | `HIDEABLE` in `billing.py`, `LAYOUT_GROUPS` in `frontend/src/billing/billLayout.ts`, and the check for it in **both** `BillDocument.tsx` and `billing_pdf.py` (a test fails if any of the three disagree) |
| a bill's own header details | `clean_header_fields` in `billing.py`, `HeaderFieldIn` in the router, `HeaderField` in `types.ts`, the ids block of **both** `BillDocument.tsx` and `invoice_pdf` |
| a bill's extra client details | `clean_party_fields` and the `last_for_client` query in `billing.py`, `party_fields` in `types.ts`, the Billed to block of **both** `BillDocument.tsx` and `invoice_pdf`, and `pickCase` in `BillEditorPage.tsx` |
| how a bill's lines are worked out or laid out (basis, days, own columns, column names, total row) | `clean_line_setup`, `clean_lines` and `compute_bill` in `billing.py` **and** `calculate`, `linePaise` in `billCalc.ts` (new vectors in `bill_vectors.json`), `LineSetup` and `BillLine` in `types.ts`, `LineSetupIn` / `LineIn` in the router, `lineColumns` in `billLayout.ts` **and** `line_columns` in `billing_pdf.py`, the lines table of **both** `BillDocument.tsx` and `invoice_pdf`, `BillLinesEditor.tsx`, and `bill.line_setup` in `migrate_bill.sql` |
| what the service charge is taken of (`service_on`) | `SERVICE_BASES`, `clean_line_setup` and `compute_bill` in `billing.py` **and** `calculate` in `billCalc.ts` (vectors), `LineSetup` in `types.ts`, `LineSetupIn` in the router, the Segmented under the charges in `BillEditorPage.tsx` |
| the charges, and figures that can be entered instead of calculated | `compute_bill`, `clean_lines`, `clean_manual_figures` and `MANUAL_KEYS` in `billing.py` **and** `calculate` in `billCalc.ts` (new vectors), `total_lines` in `billing_pdf.py` **and** `totals` in `BillDocument.tsx` (a charge prints at 0% when entered), `ManualFigures` / `BillLine` in `types.ts`, `LineIn.amount_manual` / `skip` and `BillIn.manual_figures` in the router, `ChargeAmount` and `LineFields` in the editor, `enteredNotes` in `BillViewPage.tsx`, `bill.manual_figures` in `migrate_bill.sql` |
| a bill's tender ID and start date | `tender_id`, `tender_start_date` in `migrate_bill.sql`, `_clean_bill` and `list_cases` (the case's opportunity supplies them) in `billing.py`, `BillIn`, `types.ts`, the invoice box of **both** `BillDocument.tsx` and `invoice_pdf`, `HIDEABLE` / `LAYOUT_GROUPS` (`tender_id`, `tender_date`), `BillEditorPage.tsx` |
| how a bill's charges print | `total_lines` in `billing_pdf.py` **and** `totals` in `BillDocument.tsx`; extra charges also in `compute_bill` and `calculate` (they count towards the taxable value) |
| what is printed | `BillDocument.tsx`, and `billing_pdf.py` (below). It is drawn in fixed colours and its own font; the app theme must not reach it |
| the bill's totals or case | nothing by hand: `_sync_revenue` updates the revenue rows. Call it after any new kind of change to a bill |

What is printed also exists in a second place: `backend/app/billing_pdf.py` draws the invoice PDF that is emailed
and downloaded, and the statement PDF. It repeats `BillDocument.tsx`'s sections and `rupeeWords.ts`'s wording, so a
change to either of those is a change to `billing_pdf.py` too. `test_receivables.py` checks the amount in words and
that both PDFs build, not their layout: look at one.

Outstanding and Monthly billing read bills, so they follow a change to these:

| If you change | Also check |
|---|---|
| what counts as received or owed on a bill (`received_total`, the `Committed` / `Prospective` rules) | `receivables.list_receivables` repeats the received sum; keep it equal to `LIST_COLUMNS` |
| a bill's `status`, `case_code` or `client_code` rules | `list_receivables` (issued and tagged only) and `list_due_to_bill` (latest issued bill per case) |
| the age buckets (`BUCKETS`) | `bucket_labels` is sent to the UI, which draws one tile and one column per label |
| the message wording or the recipient rules | `receivables.py` only; the dialog shows what the server sends |
| the `bill_message` table | `migrate_bill.sql`, `receivables.py`, `ShareHistoryRow` / `ShareDefaults` in `types.ts` |

Old versions are stored as a JSON snapshot of the row. A column added later is **absent** from snapshots taken
before it existed, so the view page must tolerate a missing field when showing an old version.

### Warehouse loads and record history

| If you change | Also check |
|---|---|
| a warehouse spec's `attrs` / `compare` | what counts as a new version, and so what History can show. History compares the form's fields that are also in `dw_cols`, so a field on the form but missing from the spec never appears in history |
| a dimension's reference to another record | store the other record's **code** in the dimension, as `manager_code` and `capability_head_code` do. Add a surrogate key only on a fact, and only if reports need it: add it to the fact's `pit` function in `dw_sync.py` through the `_PIT` index of the dimension it points at |
| the warehouse load order or the specs | `source_fingerprint` (it reads every spec's ODS table) and `load_status` (it counts every table in `REFRESH_ORDER`) |
| how a load is started | go through `etl.start_run`: it takes the one-at-a-time lock and writes `etl_run`, which the "last loaded" note, the automatic loader and the ETL page read |
| `ORION_DW_AUTOLOAD_MINUTES` | `.env.example`, `deploy/env.prod.example` and the real `.env` on each machine |
| `record_history.py` output | `RecordHistory` / `HistoryEntry` in `types.ts` and `RecordHistoryModal.tsx` |
| a column of a warehouse table | it is listed on the warehouse page by itself: `dw_sync._listing` builds the listing from the spec's `dw_cols`, and `tally_dw.dw_preview` adds every column found in the table. A column that must be hidden from some readers goes in the spec's `private` list |
| a date a fact is linked to the calendar by (`keys["date_sk"]` in a `_pit_*` function) | `_FACT_DATES` in `dw_sync.py` (and the voucher query in `tally_dw._calendar_bounds`), or facts with a date outside the calendar drop out of every report that joins to it; `test_integrity_fixes.py` checks the two agree |
| how a fact finds its bill (`_pit_case_txn`) | the bill is looked up by `latest`, not as at the entry's date; a bill edit must reach the entry at the next load |
| `grants.sql`, or what the application role owns | `db_grants.needed()`: it decides whether the script runs at all; if a new schema is added it must be in its list |

### ETL pipelines and their history

| If you change | Also change |
|---|---|
| add a pipeline | a `Pipeline` in `etl.pipelines()`, its key in the `CHECK` of `etl_run.pipeline` (`migrate_etl.sql`) and in `EtlPipelineKey` in `types.ts`; a test checks all three |
| add or remove a table in a loader's `REFRESH_ORDER` | nothing: the pipeline's steps are read from it |
| what a loader returns from a table load | `etl.normalise` maps its keys to read / inserted / updated / deleted / unchanged; a new key is ignored until added there |
| the columns of `etl_run` / `etl_run_step` | `migrate_etl.sql`, `etl.py` (`RUN_COLUMNS`, the inserts and updates), `EtlRun` / `EtlStep` in `types.ts`, `RunDetailModal.tsx`, `RunHistory.tsx` |
| the run triggers | the `CHECK` in `migrate_etl.sql`, `etl.TRIGGERS`, `TRIGGER_LABEL` in `etl/format.ts` |
| a way of starting a load that is not `etl.start_run` | don't: the run would not be recorded and the one-at-a-time lock would not apply |
| a schedule for a Tally pipeline | call `etl.start_run(..., trigger="scheduled")` from a thread like `dw_auto.py`, and update the pipeline's `schedule` text |

Resetting `orion_ods` erases the run history with everything else in it.

### Orion dashboards

The backend sends named blocks; the frontend asks for them by name. Nothing checks the names match.

| Declared in the backend | Used in the frontend | Caught by a test |
|---|---|---|
| view names, `VIEWS` in `dashboard/views.py` | tabs in `frontend/src/dashboards/registry.ts` | Yes |
| a tab's KPI keys, `kpiKeys` in `registry.ts` (their order decides which figures are the headline cards: the first three, or two on a tab with five or fewer) | `KPI_HELP` in `dashboard/kpi_help.py`; the figure itself in `engine.Dash.kpis` or the view's own `kpis` | Yes: every figure a tab shows needs help text |
| a drill-down, `MEASURES` in `dashboard/explore.py` (Orion) and `tally_explore.py` (Tally) | the tile's `explore` flag and `MeasureExplorer.tsx`; its help in `kpi_help.py`; its record sets in `records.py` | Yes: dimensions must be on the fact's scope, record sets must exist, help must exist. A tile's definition in `engine.py`, its drill-down in `explore.py` and the rows it lists (`population`) are written separately and must say the same thing: change a definition in all three |
| record sets, `DATASETS` in `dashboard/records.py` | the "Explore records" menu and each chart's Records button (`records('bills', ...)` in the pages) | Partly: the sets are checked, the page ids are not |
| block ids in each builder (`series`, `categories`, `tables`) | `series('trend')`, `categories('by_domain')`, `table('...')` in `pages/dashboards/*.tsx` | No: a wrong id renders an empty chart |
| KPI `key` | icon lookup in `dashboards/kpiIcons.tsx` | No: a missing key gets a generic icon |
| KPI `tone` | icon tint in `components/dashboard/KpiCard.tsx` | No |
| the default period or a period value (`fy=current`, `fy=all`), `windows.resolve_fy` (read by `Dash` and by `tally_dashboard`) | `requestFilters`/`effectiveFilters`/`usePeriodControls` in `dashboards/useDashboard.ts`, `FilterDock`, the Copilot's page context (`ai/pageContext.ts`, `safety.sanitize_context`). Whatever reads the screen's filters (the rows drawer, the drill-down, the Copilot) must use the *effective* filters, not the address, or it shows all time while the screen shows a year | Yes: `test_dashboard_periods.py` (windows; the dashboards with `ORION_DASHBOARD_DB_TESTS=1`) |
| how a year in progress is compared, `comparison_windows` (its dict has `previous`, `yoy`, `full`) | `Dash.full` and `period_kpi`, Tally's `compare()`, `meta.comparison` (`full`, `kind`), `KpiChange` and `DashboardKpi.full` in `types.ts`, `dashboards/compare.ts` (`withCompare`), `MetricCard` (the second line, `AlsoBlock`) | Yes |
| a chart's tooltip or a hover card | use `TipCard` (chart) and `HoverCard`/`.tip-surface` (card); series colours go in a swatch only, never in the text; a multi-series chart binds each series with `useSeriesFocus` and uses `SeriesTip` so the trend follows the hovered series; `test_tooltips.py` checks it | Yes |
| a dashboard page's layout | rows of cards must add up to the grid's columns; use `ChartCard`, `Empty` (`data-empty`) and `CategoryBar` so a card does not leave a hole beside a taller one | No: look at the page at 1100, 1500 and 1900 px wide |
| filter keys, `FILTER_KEYS` in `dashboard/filters.py` | `DASHBOARD_FILTER_KEYS` in `types.ts`, the URL query string, the groups in `pages/dashboards/DashboardShell.tsx` (`FilterDock` shows only what is listed there) | Yes |
| series colours | `SERIES` in `components/dashboard/format.ts`, named per measure | No |
| a figure on the Forecast tab (`METRICS` in `dashboard/forecasting.py` or `tally_forecast.py`) | the figure's monthly series (`trend` / `cash_trend` / `_monthly` / `_document_trend`): a change to how the dashboards define it moves the forecast too, and the tab's labels and means; the Copilot's `get_forecast` enums (`ORION_METRICS`, `TALLY_METRICS` in `ai/tools/forecast.py`) and `DashboardView`-independent types `ForecastMetric` in `types.ts`. `test_forecast.py` (with `ORION_DASHBOARD_DB_TESTS=1`) builds both against the warehouses |
| the forecasting statistics (`app/forecast.py`: models, the back-test, the range, confidence, cleaning) | `test_forecast.py`, which checks that a trend, a season and a level shift are recovered and that the 80% range holds about 80% of simulated months: change a threshold and that calibration test on purpose. The words the page uses for confidence and skill (`ForecastBoard.tsx`, `forecast._confidence`) and "How this was worked out" in `docs/features.md` |
| a tab with its own page and endpoint (`standalone: true` in `registry.ts`, today `forecast` on both dashboards) | the route in the dashboard router **before** `/{view}`, the Tally router, `workspaceRoutes.tsx`, and the contract test in `test_contracts.py`, which lets a tab be stand-alone only if both endpoints exist |
| a tab only some people may see (`RESTRICTED_VIEWS` in `dashboard/__init__.py`, today `cash`) | the router's `view_allowed` and `views_for`, every Copilot tool that reads or opens a dashboard (`OPEN_VIEWS` in `ai/tools/analytics.py`, `view_allowed` in `ai/tools/actions.py`), and the tab filter in `DashboardShell.tsx`. A tab shows data, so a new way of reading a view needs the same check | Partly: `test_bank.py` checks the routes, not every tool |

A filter key is also a contract with each fact's scope in `filters.py`: a key a fact does not list is ignored
for that fact. Adding a filter means deciding, per fact, whether it applies.

### Tally

A straight pipeline. Each stage names its columns by hand.

`tally_client.py` (parse XML) -> `tally_ods.py` (loaders) + `tally_ods_schema.sql` -> `tally_dw.py` (specs) +
`tally_dw_schema.sql` -> `tally_dashboard.py` (SQL) -> `frontend/src/pages/dashboards/tally/*`

| If you change | Also change |
|---|---|
| a field read from Tally | every stage to the right of it that should carry it |
| a Tally KPI | the Copilot's Tally tools too: `ai/tools/tally.py` (`TALLY_METRICS`) reads `tally_dashboard.py`'s `_aggregates`, `_monthly`, `_top_clients`, `_income_from_lines`, `_debtor_*` and `_books_position` by name, so renaming or re-shaping one breaks them (`test_ai_tally.py` patches them). Its key in `tally_dashboard.py`, `kpiKeys` in `registry.ts` (`TALLY_DASHBOARDS`), its help in `tally_kpi_help.py`, its icon in `kpiIcons.tsx` |
| a Tally filter | the Copilot's filters (`FILTER_KEYS`, the name look-ups in `ai/tools/tally.py`) and its page context (`safety.sanitize_context`). `FILTER_KEYS` in `tally_dashboard.py`, validation in `tally_insights.py`, `DASHBOARD_FILTER_KEYS` in `types.ts`, the groups in `pages/TallyDashboardPage.tsx` |
| the data model | `.cursor/db/tally_ods_data_model.md`, `tally_dw_data_model.md` |

Not covered by the contract tests. `backend/tests/test_tally_insights.py` covers the pure helpers only. Tally
can be exercised only on the office PC.

### Notifications for won opportunities (`opportunity_followups.py`)

| If you change | Also change |
|---|---|
| what makes a follow-up done (a case or an EMD "exists") | `CASE_EXISTS` / `EMD_EXISTS` in `opportunity_followups.py`; they are used by every statement of `sync`, so the notification, its settling and its reopening stay one rule. If a new kind of record can stand for a case or EMD, add it there |
| a new kind of notification (another thing to do after a win) | a kind in the `CHECK` of `migrate_followups.sql`, the `kind` rows `sync` creates, `_shape` (title, message, action), the bell's icon, and the form the action opens |
| the address a notification opens | `_shape` builds `/data/operational?intent=change&entity=…&mode=create&opportunity=…`; `OperationalDataPage.tsx` reads exactly those names (`startFollowup`), and a test compares them |
| the Case or EMD form's fields | the follow-up prefills `case_name` (Case) and `case_code`, `tender_reference` (EMD) and fixes `opportunity_code`: rename one of those and `startFollowup` and `EntityForm`'s `lockedFields` / `optionOverrides` follow |
| the opportunity statuses, or what "won" is | `WON` in `opportunity_followups.py` (`Closed Won`) and the Pipeline dashboard's won rules, which read the same status |
| who may see the notifications | `followups_router.py` (every route `require_ods_write`, a test checks it) and `FollowupsContext` (it asks only when `can_ods_write`) |
| a new way of saving opportunities, cases or EMDs | call `opportunity_followups.entity_saved(...)` or `sync_quietly()` after it, as `entity_service` and the Excel upload do; the bell's own minute-by-minute look catches the rest |

### Attendance (`attendance.py`)

| If you change | Also change |
|---|---|
| how a line's amount is worked out | `attendance.calculated_amount` and `frontend/src/attendance/attendanceCalc.ts` together, and `backend/tests/attendance_vectors.json` on purpose (`test_attendance.py`, `npm run check:attendance`). The rate is kept to four decimals, the days to one, the money to paise |
| what posting enters | `attendance.post_sheet` (the columns of the salary line and the expense), `attendance.reopen_sheet` (what it takes back and when it refuses), `entities.locked_reason` (the entries are locked while the register stands), the posting screen's wording in `AttendanceModals.tsx` and this section's rules |
| a column of `employee_transaction` or `expense_transaction` that posting writes | `post_sheet`, and a new column that must be set for the generic forms must be set here too; the lines are not made through `entity_service` |
| paying (a pay run, a payment on an expense) | `reopen_sheet` reads `salary_run_id`, `salary_paid` and `expense_payment` to refuse; if a new way of paying is added it must be read there too, or a paid register could be reopened |
| the case a salary line belongs to | `employee_transaction.case_code` (set by posting), `payroll.unpaid_lines` (`COALESCE(t.case_code, e.employee_case_code)`), `dw_sync._pit_employee_txn` and the `case_code` column of `fact_employee_transaction`, and the Payroll pay screen's case chooser |
| who may use Attendance | the flags `attendance_access` / `attendance_write` (see "A new access flag" below; `test_attendance.py` checks every route), the rail item in `Layout.tsx`, the route in `workspaceRoutes.tsx` and the `/attendance/*` prefix in `App.tsx` (without it the address redirects home) |
| the people who are not employees | `attendance_worker` and `attendance.create_worker` / `update_worker`; they are never added to `employee`, and a register's line keeps the name and work as they were |
| the Excel template or its headings | `attendance.COLUMNS`, `template_file`, `parse_upload` and `sheet_file`, which share them |

### Tasks (`tasks.py`, `task_*.py`)

| If you change | Also change |
|---|---|
| who may see or change what in a project | `task_common.role_in`, `need_view` / `need_edit` / `need_manage`, `visible_sql` (the list queries), `can_work_in` (who a task may be given to), `can_see_project_id` and `task_notify.notify` (who may be told): they must all say the same thing, or a private project leaks through a list, a search, a report or a notification. `test_tasks.py` (privacy) checks it |
| a status kind, the default workflow or what "done" means | `task_common.CATEGORIES` / `DEFAULT_STATUSES`, the `CHECK` in `migrate_tasks.sql`, `tasks.transition` / `decide_review` (resolution, review, blockers), `task_sprints` (what counts as finished), `task_views.reports` and `board`, and the colours in `taskUi.tsx` and `BoardView.tsx` |
| a column of `orion_ods.task` | the `TASK_COLUMNS` and `task_json` in `tasks.py`, `TaskCard` / `TaskDetail` in `types.ts`, the `TaskChanges` model in `tasks_router.py` (it forbids unknown fields) and `update_task`'s allowed list, the new-task form and the drawer, `task_templates._task_data` if a template should carry it, and `task_activity` wording in `task_items._words` |
| a filter or a sort of the task list | `FILTER_NAMES` in `tasks_router.py`, `tasks.list_tasks` (every value a parameter, every column from `SORTS`), `TaskFilters` in `types.ts`, `FilterBar.tsx`; `test_tasks.py` has the injection test |
| a notification kind | `task_notify.notify` callers (the text is stored, so an old one keeps its words), `TasksBell` / `InboxPage` (they only show the text), and who is told (`task_items._interested`) |
| a new way to make a task (a button on a bill, a document-expiry reminder) | call `tasks.create_task` (or `insert_task` inside your own transaction) with `records` to link the record; do not write `orion_ods.task` yourself. The record link is only added when the person may see that kind of record |
| a new kind of record a task may point at | `task_common.RECORD_TYPES`, `task_items.RECORD_SOURCES` (the lookup and who may see it), the `CHECK` on `task_record_link.record_type`, `RECORD_KINDS` in `TaskPanels.tsx` |
| the repeating schedule | `task_templates.first_run` / `following` / `describe` (pure, tested), the `CHECK`s on `task_template`, `TemplatesView.tsx`; the job is `task_templates.start`, called from `main.py`'s lifespan |
| a new table `task_*` | add it to the `OWNED_TABLES` pattern in `sql_guard.py` (it already matches `task` and `task_*`), and name its single writer module in the docstring of `task_common.py` |
| a limit (title, labels, comment, files) | the constant in `task_common` / `task_items` / `task_files`, and the matching `maxLength` / `max` on the screen (`NewTaskModal`, `TaskDrawer`, `TaskPanels`, `TemplatesView`): the screen must show the limit the server enforces |
| the rail item, the route or the bell | `NAV_GROUPS` in `Layout.tsx`, `tasks` in `TabMemoryContext.tsx`, `WorkspacePanes.tsx`, `workspaceRoutes.tsx` (`tasksRouteTree`), the `/tasks/*` placeholder in `App.tsx`, `ai/pageContext.ts`; the numbers come from `GET /api/tasks/me` through `TasksContext` |

### Uploading a folder (`documents.ensure_folder_paths`, `uploadFolders.ts`)

| If you change | Also change |
|---|---|
| `MAX_FOLDER_DEPTH`, `clean_folder_name` or the folder-name rules | `folderName` in `uploadFolders.ts` (it tidies a name the same way, so the path the page sends is the path the server reads), `plan_folder_paths` and `test_documents.py` |
| the file types or the size limit (`FILE_TYPES`, `check_file`) | `problemWith` in `UploadModal.tsx` (a folder's unsupported files are dropped there, by the message that begins "A file of that type") |
| the unique folder-name index `ux_doc_folder_name` | `ensure_folder_paths` looks a folder up by `lower(name)` under its parent and relies on that index (`ON CONFLICT DO NOTHING`) |

### SQL editor (`sql_lab.py`, `sql_guard.py`)

| If you change | Also change |
|---|---|
| what may run (a statement kind, a schema, a function) | `sql_guard.py` (`READ_WORDS`, `WRITE_WORDS`, `STRUCTURE_WORDS`, `NEVER_WORDS`, `BLOCKED_FUNCTIONS`) and `test_sql_editor.py`; the explanation on the page (`SqlEditorPage` banner and the Allow-changes confirmation) and `docs/features.md` |
| a new table that holds secrets or private messages | `PRIVATE_TABLES` (never readable); a new table whose rules live in application code (written by one module) | `OWNED_TABLES` (readable, never written by SQL) |
| a column added to `app_user` | `reports.users` in `migrate_sql_lab.sql` if it is not secret (it is a fixed list of columns) |
| how a run is made (transaction, limits) | `sql_lab.run` and `export_csv`; a run must stay: guard first, then the connection, then an audit row (`_log`) whatever happens |
| a new route | `require_sql` on it (a test fails otherwise) |

### Column filters (`column_filters.py`, `tables/columnFilter.ts`)

| If you change | Also change |
|---|---|
| an operator, or what a kind of column can be asked | `OPS` in **both** `column_filters.py` and `tables/columnFilter.ts` (and `OP_LABEL`, `matchesFilter`); `test_column_filters.py` and `npm run check:filters` |
| a new table of data that lists rows | render it with `DataTable` / `ReportTable` / `RecordTable` and it has filters; a server-paged one passes `f` through to `db_utils.fetch_preview_ex` and has a `/values` route like the four in `entities_router`, `dw_router`, `tally_router`, `tally_dw_router` |
| a dashboard record set (`dashboard/records.py` `DATASETS`, `tally_explore.VOUCHER_COLUMNS`) | its columns' `expr` and `format` are what the filters use (`kind_of_format`); a set worked out in Python must answer `filterable: False` |
| a column that must not be seen by some people | leave it out of the preview's source (`source_without`), as now: the filters can then not reach it |

### Google Drive (`gdrive.py`, `gdrive_client.py`)

| If you change | Also change |
|---|---|
| what a Drive can do | `DriveClient` in `gdrive_client.py` and **both** `FakeDrive` and `GoogleDrive` (the fake is how everything is tested and shown; a method on one only breaks the switch to Google); `test_gdrive.py` |
| which Drive is used / a new setting | `gdrive_client.configured_mode`, `startup_checks.google_drive_problem`, `.env.example`, DEPLOYMENT.md "Google Drive" |
| what may leave Orion | `gdrive.copy_to_drive` (Confidential, filed papers, size) and the confirmation in `DocumentCenterPage.sendToDrive`; never send a document from a screen that skips them |
| a Drive place in the address (`gdrive`, `gdrive:<id>`) | `components/documents/driveNodes.ts`, `ExplorerTree`, `DriveSection`, `FolderPicker` (`source="drive"`), `DocumentCenterPage` (`isDrive`) |
| when a bill is saved, edited, cancelled or its text size changed | the router calls `gdrive.sync_bill_quietly` (billing_router: create via `after_bill_created`, update, cancel, font); a new way to change a bill must too |
| the schema | `migrate_gdrive.sql`: `gdrive_connection`, `drive_link` (and its two unique indexes: `ON CONFLICT` in `gdrive._add_link` must match `ux_drive_link_file`) |

### The Document Center explorer (`documents_explorer.py`)

| If you change | Also change |
|---|---|
| a kind of place (a node: `root`, `company`, `clients`, `cases`, `client:`, `case:`, `folder:`, `all`, `trash`) | `documents_explorer._NODE`, `resolve`, `_document_filters`; `ExplorerKind` in `types.ts`; the tree (`ExplorerTree.tsx`), the page's `go`/`flat`/`placesOnly`, `legacyNode` (old addresses) and `FolderPicker.tsx`; `test_documents_explorer.py` |
| what a folder shows | `documents._in_space` (`exact` is the folder's own, otherwise everything inside it) and `documents_explorer.browse`; the folder counts are `documents.list_folders` |
| how things are moved | `documents.move_items` / `move_folder` (the only writers), `documents_explorer.move` (a filed paper goes through the filing, not here), `POST /documents/move`, `moveDocuments` in `client.ts`, and every drop target (`ExplorerList`, `ExplorerTree`, the breadcrumb in `DocumentCenterPage`) |

### Documents filed automatically (`documents_filing.py`)

| If you change | Also change |
|---|---|
| a new kind of thing to file (a letter, a statement, a new record's files) | `documents_filing.py`: its rows query, a `*_places` function (home and other places; every path at most `documents.MAX_FOLDER_DEPTH` deep), a `Filing` builder, its `CATEGORY` (which must exist in `documents.CATEGORIES` for the home space), a `source_type` in `documents.SOURCES` (the label and the page), the `reconcile` and `_retire` queries, and a hook after the thing is saved (`reconcile_quietly(...)`) |
| deleting a folder with its contents (`documents.folder_contents` / `drop_folder`, `DropFolderDialog`, `remove` in `DocumentCenterPage`) | the warning and the deed are one rule: `can_drop` decides both, and the `seen_*` numbers must match when the drop runs. A new kind of thing that can live in a folder (a new table with a `folder_id`) must be counted in `folder_contents` and dealt with in `drop_folder`, or a drop will leave it pointing at a deleted folder or silently lose it. Filed papers and Orion's own folders are refused there, never worked around. `test_documents_drop.py` (set `ORION_DOC_DB_TESTS=1`) |
| where a bill, an EMD's or an employee's papers go | `bill_places` / `emd_places` / `employee_places`; a folder key is the identity of a folder, so changing a key makes a **new** folder and leaves the old one empty until `_retire` removes it. Change the `layout` string of the source so the old documents are refiled |
| what makes a bill's PDF change | `_bill_content` (a new PDF is a new version only when this changes). The PDF itself is `receivables.invoice_document(code, False)`; a change to `billing_pdf.py` alone does not refile old bills |
| the name of a case, client or employee, or an employee's case | the `layout` strings (`_bill_layout`, `_employee_filing`, `_emd_filing`) and the `entity_saved` hook in `entity_service.change` / `remove`, which refile what depends on it |
| what a person may do to a filed document | `documents.refuse_filed` is called by `update_document`, `add_version`, `restore_version`, `set_deleted` and `bulk_update`; a new writer of `document` must call it too. The page hides the buttons (`DocumentDrawer.tsx`), the server decides |
| which documents a space shows | `documents._in_space` (home **or** placement, and a folder with everything inside it), `documents.spaces` (`_APPEARANCES`) and `list_folders`. A new filter on a space must treat placements |
| where a person keeps a filed paper | `document_filing_choice` (`documents_filing.set_choice`, `_choose`, `_load_choices`; the choice is in each source's `layout` so changing it refiles), `documents_explorer.move` / `choose_for_source` / `locations`, `BillIn.filing_node` in `billing_router.create`, `BillFiling.tsx` / `BillFiledIn.tsx`, and the three `*_filing` builders (a new kind of source must take `row["choice"]` the same way) |
| the schema | `migrate_documents_filing.sql`: `document.source_*`, `doc_folder.system_key`, `document_placement`, `document_filing_choice`; the placement's `ON CONFLICT` in `documents_filing._place_documents` must match its unique index |

### The Document Center

| If you change | Also change |
|---|---|
| the kinds of document (`CATEGORIES`) | `documents.py` only; the browser gets them from `/documents/options`. A document already filed under a kind you remove keeps it, but cannot be saved again until its kind is changed. `CASE_CHECKLIST` must stay a subset of the case kinds (a test checks) |
| the file types accepted | `FILE_TYPES` in `documents.py` (it extends `employee_documents.FILE_TYPES`, so a type added there is accepted here too) and, for search, `extract_text`. Never mark a type that can run script in a browser as inline (`employee_documents.is_inline`) |
| a column of `document` | `migrate_documents.sql`, `_SELECT` and the INSERT/UPDATE in `documents.py`, `DocumentSummary` / `DocumentInput` in `types.ts`, and the edit form in `DocumentDrawer.tsx` and upload in `UploadModal.tsx` |
| who sees a document | `documents.can_see_confidential` and every query that lists, counts or reads (`_where`, `spaces`, `overview`, `case_checklist`, `get_document`, `get_file`, `_lock`, `list_folders`). A new query must apply the same rule |
| the expiry rule | `expiry_state` (what the screen shows) **and** the `expiry` branch of `_where` (what the filter and the overview count) |
| how files are stored | `document_blob` is shared between versions and documents, so a delete must only remove a file nothing else uses (`purge_document`). Backups carry it, so a larger limit means larger backups |
| the access flags | see "A new access flag" below; the pair is `documents_access` / `documents_write` |

Document files are not part of the warehouse and not part of any ETL pipeline.

### Tenders (GeM and MP Tenders)

| If you change | Also change |
|---|---|
| how GeM is asked or read (`gem_client.py`: the listing page, the search payload, the fields of an answer, the document's labels) | `test_tenders.py` (the stand-in answers and `DOCUMENT_TEXT` are written from real ones; update them from a real answer, never from memory), the column list in `migrate_tenders.sql`, `TenderBid` in `types.ts`, `BidCard` in `TendersPage.tsx` |
| how MP Tenders is read (`mptenders_client.py`: the organisation list, an organisation's rows with their commented-out column, the details page's caption/field cells, the fee heading) | `test_tenders.py` (`MP_ORGANISATIONS`, `mp_row`, `MP_DETAILS` are cut from real pages; update them from a real page), `_store_mp_listing` / `_store_mp_details` in `tenders.py`, `TenderBid` in `types.ts`, `toApply` in `TendersPage.tsx` |
| a new portal | `tenders.PORTALS`, `PORTAL_NAMES`, `KINDS`, the `portal` and `source` checks in `migrate_tenders.sql`, a page in `workspaceRoutes.tsx`, a rail item in `Layout.tsx` and its area in `TabMemoryContext.tsx`, a `<portal>_client.py` built on `GemSession` (its pacing and errors), a `_check_<portal>` step in `run_check`, `PORTAL` and `PAGE_TEXT` in `TendersPage.tsx`, the kinds in `SearchForm.tsx`, the filters that apply to it in `BidFilters.tsx` |
| which bids a search wants (`tenders.decide`, `type_matches`, `city_of`, `value_ok`, `questions`) | the Rules in features.md "Tenders (GeM)" and the hints in `SearchForm.tsx`, which tell people what each box does |
| a column of a `tender_*` table | `migrate_tenders.sql`, the SQL in `tenders.py`, `types.ts`, `.cursor/db/data-model.md`. Nothing in it is in the warehouse |
| how GeM is asked (`questions`, the search payload's filters or sort) | `tender_question_bid` remembers answers under the question's text and kind: a change to what a question means (another sort, another status filter) must clear that table and `tender_question`, or later checks stop early on bids the new question never returned |
| the flags (`tenders_access`, `tenders_write`) | see "A new access flag" below. A new Tenders route needs `require_tenders` (read) or `require_tenders_write` (change) and `test_tenders.py` checks both |
| `ORION_TENDERS_CHECK_HOURS`, `ORION_TENDERS_REQUEST_GAP_SECONDS`, `ORION_TENDERS_LOOKBACK_DAYS` | `.env.example`, `deploy/env.prod.example` and the real `.env` on each machine. Keep the gap at 2 seconds or more: GeM is a public site |

### The Bank

| If you change | Also change |
|---|---|
| what counts as money in or out (a branch of the view `bank_movement` or `bank_expected`) | `.cursor/db/migrate_bank.sql` (the view is replaced at every start, so it must stay a complete definition), `SOURCES` / `SOURCE_LABELS` in `bank.py`, the `source` check in `bank_match` and `bank_match.candidates` consumers, `BankLedgerRow` in `types.ts`. A source that can be reversed or cancelled elsewhere must drop out of the view when it is, or the balance keeps counting it |
| the table a movement is read from (`case_transaction`, `expense_transaction`, `bill_gst_payment`, `bill`) | the view above. Billing's "a revenue entry with a `bill_code` belongs to its bill" rule means the Bank only **reads** it; the Bank never writes these tables. A change to how a payment is dated (`received_date`) or what its amount includes (`amount_after_tax_gst`) changes every balance |
| the categories (`bank.ENTRY_CATEGORIES`, `SYSTEM_CATEGORIES`) | the lists reach the screens from `/api/bank/meta` (no frontend list to edit); `bank_match.RULES` (a test fails if a rule names a category a person cannot choose); `INCOME_CATEGORIES` if it earns; the Copilot's `search_bank_ledger` enum; the help text of the Cash figures (`kpi_help.py`). A category already on an entry that you remove keeps showing its key |
| what counts as interest and other income | `bank.INCOME_CATEGORIES`, the SQL in `bank.summary`, `series`, `other_income`, `views_cash.py`, `ai/tools/bank.py` and the help text of `bank_other_income` |
| the balance's definition (opening date, what is counted) | `bank._balance`, the window in `bank.ledger` (its running balance), `summary`, `series`, `forecast` (all repeat "from the opening date to today"), `reconciliation`, and the Account tab's confirmation (`preview_account_change`). They must agree: `test_bank.py` (with `ORION_DB_TESTS=1`) checks the ledger's last balance equals the account's |
| matching (`AUTO_DAYS`, scores, what counts as certain) | `bank_match.py` and `test_bank_match.py`. Raising what is matched on its own is the dangerous direction: a wrong automatic match hides a real difference |
| the statement formats understood | `bank_statement.py` (`SYNONYMS`, `FIELD_ORDER`) and the column pickers in `StatementUpload.tsx` (`FIELDS`); `_mapping` in `bank_router.py` accepts only `SYNONYMS` keys |
| a column of a `bank_*` table | `migrate_bank.sql`, the SQL in `bank.py`, the type in `types.ts`, `.cursor/db/data-model.md`. Nothing in it is in the warehouse |
| what makes a match stop holding (`_EXCEPTION_SQL` in `bank.py`: the movement gone from `bank_movement`, or its amount different from `bank_match.amount`) | a new source of movement needs a branch in `_why_it_broke` (its status table, so the reason is plain words); `exceptions`, `_exception_count`, `clear_exception`, the Reconcile panel (`Changed` in `BankReconcilePage.tsx`) and the Overview and Cash-tab counts all read the same query |
| the account a money event touched (`account_id` on `case_transaction`, `bill_gst_payment`, `bank_entry`, `bank_statement_line`; the `account_id` column of `bank_movement`) | a new source of movement must name its account and be read by the view with `COALESCE(account_id, first account)` until it has one; `bank._balance`, `ledger`, `summary`, `series`, `reconciliation` and the matching helpers all scope by account (a line matches only its own account's movements); `billing._checked_account` and the payment forms (`AccountPicker.tsx`) for anything that records a receipt or a payment; a cash account never takes a statement (`_need_statement_account`) |
| the flags (`bank_access`, `bank_write`) | see "A new access flag" below. A new Bank route needs `require_bank` (read) or `require_bank_write` (change) and a test checks both; the Cash tab, the Copilot's bank tools and the rail item follow the same flag |
| money entered or imported by the Bank | only `bank.py` writes the `bank_*` tables. A new way of recording money takes an `Idempotency-Key` (as `create_entry` does); an entry is voided, never deleted |

Bank data is not part of the warehouse and not part of any ETL pipeline. It is in the nightly backup (it is in
`orion_ods`).

### The letterhead

| If you change | Also change |
|---|---|
| where a strip sits, or a spacing setting | `letterhead.layout` and `SETTING_LIMITS` (the browser gets them as `design.layout` and `design.limits`), **and** `Letterhead.boxes` / `text_space` in `letterhead_page.py` for the PDFs (a test fails if the two disagree); the fields on `LetterheadDesignPage.tsx`; `LetterheadSettingKey` in `types.ts` |
| what a letter's text may contain | `_INLINE`, `_BLOCK`, `_VOID`, `_RENAME` and `_attributes` in `letterhead.py`, **and** `KEEP`, `RENAME` and `cleanNode` in `components/letterhead/richText.ts` (a test fails if the tag lists differ); the `.lh-body` rules in `index.css` so the new tag looks right on screen and in print; a tool for it in `LetterToolbar.tsx` |
| how a letter prints | `LetterheadPrint` in `LetterheadSheet.tsx` and the `lh-*` print rules in `index.css`. Check with a letter of three or more pages: the strips must repeat and the text must stay clear of them on every page |
| a field of a letter | `orion_ods.letter` (`migrate_letterhead.sql`), `clean_letter` and `_LETTER_COLUMNS` in `letterhead.py`, `LetterIn` in the router, `LetterInput` / `LetterSummary` in `types.ts`, `LetterEditorPage.tsx` |
| what a bill leaves off on the letterhead | `invoice_pdf` and `statement_pdf` in `billing_pdf.py` only. The bill on screen (`BillDocument.tsx`) is never drawn on the letterhead: with the letterhead on, Print uses the PDF |
| the letterhead shipped with the application | `backend/app/assets/letterhead/header.jpg` and `footer.jpg`. A database where an admin has uploaded a replacement keeps showing the replacement |

The print stylesheet hides everything except `.bill-print-root` and `.lh-print-root`. Workspaces stay mounted, so a
bill page left open still has its `.bill-print-root` in the document while a letter prints: `body.lh-printing`
hides it. A third thing that prints needs the same care.

### PDF tools

| If you change | Also change |
|---|---|
| add a tool | a function in `pdf_tools.py` and its entry in `TOOLS` (id, label, kind: `pdf` one file, `pdfs` two or more, `images`); its entry in `pages/pdftools/tools.ts` (id, title, blurb, `accept`, the fields it asks and their defaults, `action`, `missing`); a test in `test_pdf_tools.py` on real files. `TheScreenAndTheServerAgree` fails when the two lists, the kinds or an option name differ |
| an option a tool reads | the same name in `tools.ts` (`key`) and the default; the test for it. An option the screen sends that the server never reads is caught by the contract test |
| a limit (`MAX_FILE_BYTES`, `MAX_TOTAL_BYTES`, `MAX_FILES`, `MAX_PAGES`...) | `GET /pdf-tools/limits` sends them to the screen (nothing else to change); the size guard in `main.py` follows `MAX_TOTAL_BYTES`; the sentence on the home screen and the rules in `features.md` |
| who may use the tools | `require_letterhead` in `pdf_tools_router.py` (they share the Letterhead flags on purpose: no new flag), the rail item's `visible()` in `navigation.ts` and `pdfToolsRouteTree` use the same Letterhead check. Giving the tools their own flag is a "new access flag" (see Permissions) |
| what is kept or logged | nothing is kept; a log line holds the tool, the user id and byte counts only. A test fails if a file name or password reaches a log. Keep it so: a result stays in the browser until the person leaves |
| a dependency of the PDF code (`pypdf`, `cryptography`, `reportlab`, `Pillow`) | `requirements.txt` and `constraints.txt` (the pins), then the whole of `test_pdf_tools.py`: locking and unlocking need `cryptography` (without it pypdf falls back to a provider with no AES) |
| the reportlab picture setting (`_binary_images`) | it is a global of reportlab, changed only while a picture job draws and under a lock: other PDFs (bills) are unaffected |
| `PdfFrame` / `saveBlob` (`ui/PdfPreview.tsx`) | the bill preview, the letterhead stamp and these tools all use them; the address of a blob is made and given back in one effect so React's development double-mount does not revoke it while it is in use |

### EPFO and ESIC paid on a bill

| If you change | Also change |
|---|---|
| how EPFO or ESIC is paid on a bill | only `billing.record_statutory_payment` / `reverse_statutory_payment` write it (and `_sync_statutory` keeps the bill's two running totals in step, also after an edit); the screen is `StatutoryPaid.tsx`, the requests are in `client.ts`, the rows are `bill_statutory_payment`. The server must keep refusing a request that is not confirmed or whose `seen_paid` is stale. It mirrors the GST payment code (`GstPaid.tsx`, `record_gst_payment`): change them together when the rule is the same |
| what the bill charges for EPFO or ESIC (`epf_amount`, `esic_amount`, `compute_bill`) | what is due follows it, so `_sync_statutory` refuses an edit below what was paid; `fact_bill.epf_amount` / `esic_amount` and the dashboards' "not marked paid" figures (`engine.EPF_UNPAID`, `ESIC_UNPAID`) follow; `bill_vectors.json` and `billCalc.ts` if the arithmetic changes |
| `epf_paid_amount`, `esic_paid_amount` | on `bill` and in `fact_bill` (`dw_schema.sql`, the Bill spec in `dw_sync.py`: `ods_cols`, `dw_cols`, `compare`); a new column there needs a one-time backfill of the current rows or the first load writes a new version of every bill |
| the bank view `bank_movement` (the `statutory` branch) | `bank.SOURCES`, `SOURCE_LABELS`, `SYSTEM_CATEGORIES`, `_why_it_broke`; the branch must keep the same twelve columns as the others (`test_statutory_paid.py`); the payment's `account_id` is added in `migrate_bank.sql` because `bank_account` is created there |
| what Revenue, Expense or Margin include | EPFO and ESIC charged are inside the taxable value, so inside Revenue (`engine.REVENUE`); EPFO and ESIC PAID are a cost, on the day paid, independent of payroll: the view `orion_dw.expense_cost` (in `dw_schema.sql`) adds each `bill_statutory_payment` not reversed to the expenses, against the bill's case, and the `expense` scope reads it (`filters.SCOPES`). Anything that reads expenses must go through that scope, not `fact_expense_transaction`; a new column the expense readers use must be in EVERY branch of the view. The rows' expense type is `STATUTORY` (`filters.EXPENSE_TYPE_CODE`, `EXPENSE_TYPE_NAME`). The same view adds each non-TDS deduction a client held back on a payment (`bill_payment_deduction` kind Penalty, Other, Rounding, not reversed) as a cost on the payment's day, type `SHORTFALL`; TDS stays out. A new deduction kind must say there whether it is a cost. The profit and loss (`dashboard/pnl.py`) adds up from the same scopes and must equal the headline Operating margin |
| the Controls tab's EPFO and ESIC figures | `engine.py` (two scalars, two KPIs), `explore.py` (measures, contexts), `records.py` (columns, `statutory_pending`), `views_ops.controls` (chart, table, headline figures), `insights.py`, `kpi_help.py`; and on the screen `dashboards/registry.ts`, `kpiIcons.tsx`, `ControlsDashboard.tsx` |
| Utility > EPFO and ESIC | `statutory_position.py`, `routers/statutory_router.py`, `StatutoryPage.tsx`, the tab in `UtilityPage.tsx` and the route in `workspaceRoutes.tsx` |

### API routes

| If you change | Also change |
|---|---|
| a route's path, method, body or response | `frontend/src/api/client.ts` and the type in `types.ts`; then every caller, which `tsc` will list |
| add a route | give it a dependency from `dependencies.py`; add the client function and types |
| add a router file | register it in `backend/app/main.py` |
| anything under a path that does not start with `/api` | in prod the API serves the built UI for every other path (`main.py`), so a non-`/api` route would be shadowed |

The dev server proxies only `/api` (and its WebSocket) to the API: `frontend/vite.config.ts`.

### Permissions

A new access flag touches all of these:

`app_user` column (a `migrate_app_user_*.sql` for new databases **and** `_apply_user_access_columns` in `auth.py` for
existing ones, each backfilling from what people could already do) -> `ACCESS_FLAGS` and `ROLE_DEFAULT_DATA_ACCESS`
(and `WRITE_IMPLIES_ACCESS` for a write flag) in `auth.py` -> a `can_*` function there -> a `require_*` dependency in
`dependencies.py` -> the `can_*` value in `/api/auth/me` (`routers/auth_router.py`) -> `User`, `AppUser` and
`ACCESS_FLAG_KEYS` in `frontend/src/types.ts` -> the toggles in `pages/AdminPage.tsx` and `AccessFlags` in
`routers/users_router.py` -> `visible()` in `components/Layout.tsx` and the route guard in
`components/ProtectedRoute.tsx`. Creating, updating and approving users, and the `SELECT`, `INSERT` and `UPDATE`
statements, are driven by `ACCESS_FLAGS`, so they need no change. `test_access.py` checks the list, the defaults, the
admin form and that every Billing, ETL and Bank route has its own guard (`test_bank.py` also calls every Bank route signed out, without Bank access and with read-only access); `test_letterhead.py` does the same for Letterhead.

Moving a feature from one flag to another (Billing moved from Tally to ODS, then to its own `billing_*`; loading
moved from the `*_write` flags to `etl_*`) changes who can use it: backfill the new flag from the old one, as
`_apply_user_access_columns` does, and say so in the pull request.

### The AI Copilot

| If you change | Also change |
|---|---|
| a dashboard measure, view or filter (`dashboard/`) | the Copilot reads the same engine: `ai/tools/analytics.py` (`PERIOD_METRICS`, `SNAPSHOT_METRICS`, `BREAKDOWN_METRICS`, `_resolve_dimensions`) names measures by key and `ai/insights.py` calls `build_view("overview")`. A renamed total breaks both; `test_ai.py` and the e2e check do not cover every measure |
| a chat message rule or the chat tables (`chat.py`, `migrate_chat.sql`) | `routers/messages_router.py` maps `ChatError` kinds to statuses; `ChatContext.tsx` and `useThread.ts` handle the socket events by name (`message`, `message_updated`, `reactions`, `read`, `pins`, `typing`, `chat_deleted`, `error`); `chat_ai.py` reads `chat.MESSAGE_TABLE`; `test_chat_integration.py` (needs the dev database) pins who can see and change what |
| the record rules (`entity_service.py`, `entities.py`, an entity's `form_fields`) | the Copilot creates, changes and deletes records through `entity_service`, and the entity list it offers (`ENTITY_NAMES`) comes from `entities.ENTITIES`. A new entity appears in its tools automatically; its private columns must be listed in `records._private` or they could be returned |
| a bill rule (`billing.py`) or the receivables report | `ai/tools/records.py` (`get_receivables`, `list_bills`, `get_bills_to_raise`) and `ai/reports.py` read them; the Copilot never writes a bill |
| an access flag or a `can_*` function | the tools' `needs(user)` use them: `ai/tools/*.py` and `ai/prompt.py` (`access_lines`). A flag moved or renamed changes what the Copilot offers |
| add a tool | `@tool(...)` in `ai/tools/`, with `needs`, a schema, a `label` and for a change `confirm=True` plus a `prepare` that builds the card from the validated arguments; give it a result that includes `blocks` for anything to draw; `test_ai.py` checks every tool has a schema, that risky writes are confirmed and that no tool is named like a SQL or bulk operation |
| a block kind (`ctx.block("kind")`) | `AiBlock` in `frontend/src/types.ts` and `BlockView` in `components/assistant/Blocks.tsx` (checked by `test_ai.py::FrontendContract`) |
| a streamed event or a saved part | `AiEvent` / `AiPart` in `types.ts`, `ai/transcript.ts`, `MessageView.tsx` (checked by `FrontendContract`) |
| a screen action (`navigate`, `appearance`) | `runUiAction` in `ai/AssistantContext.tsx`; the theme list in `ai/tools/actions.py` (`THEME_IDS`) must match `theme/themes.ts` (checked) |
| what the page tells the Copilot | `ai/pageContext.ts` and `safety.sanitize_context`: the server drops any key it does not list (checked) |
| a model name, limit, price or cloud setting | `ai/config.py` or the environment; nothing else may name a model (checked). A new `ORION_AI_*` variable also goes in `.env.example`, `deploy/env.prod.example` and `docs/ai-setup.md` |
| a way of recognising requests (`routing/intents.py`) | what is answered with no model at all, and what the classifier labels (`routing/classifier.py` `INTENT_CATEGORY`); `test_ai_routing.py` `Planning` and `Classifying`. A new tool a rule calls also needs a composer in `routing/compose.py` |
| how a model reads a question (`routing/interpret.py`, `routing/names.py`) | the intent menu (`MENU`) must match the cases in `to_plan`, and each intent needs words the question must contain (`EVIDENCE`) or a wrong reading is believed; client and case names come from `orion_ods.client` and `case` |
| the cloud policy, sensitivity rules or what is sent (`routing/policy.py`, `sensitivity.py`, `pseudonym.py`) | the twelve scenarios in `test_ai_routing.py` pin them (nothing leaves under local-only, sensitive, no budget, local down). Change them with the report in hand: `scripts/ai_routing_report.py` |
| a provider (`ai/providers/`) | its wire format is tested in `test_ai_routing.py` (a stand-in Ollama server; the OpenAI and Anthropic SDK shapes); a new one needs `capabilities`, `health` and `ProviderError.kind` set so the router can tell "down" from "failed" |
| `ai_policy`, `ai_route_log`, `ai_user_setting.allow_cloud` | `store.py`, `routers/ai_router.py` (status, policy, health, explain), `frontend/src/types.ts` (`AiRouting`, `AiStatus`) and `components/assistant/RoutingSettings.tsx` |
| the rules the model is given (`ai/prompt.py`) | read `test_ai.py` first: it pins the rules that matter (untrusted data, no bypass, no invention) |
| `ai_*` tables | `.cursor/db/migrate_ai.sql`, `ai/store.py`, `.cursor/db/data-model.md`; a conversation holds the user's own text, so deleting a user must also delete their conversations (`ON DELETE CASCADE` on `user_id`) |
| `AdminPage.tsx` flags or `ACCESS_FLAGS` | `ai_access` is one of them (see Permissions) |
| `ai/assist.py` (the gate) or `ai/features.py` | every AI button outside the Copilot panel goes through them: the letter editor, the receivables reminder, document upload, record forms and the ETL drawer (and message drafting in `chat_ai.py`). A change to who may be sent to a cloud model is a change to `routing/policy.py` and is checked by `test_ai_assist.py` |
| the receivables reminder wording (`receivables.py`: `_rupees`, `_bank_lines`, `day`, `month`) | `ai/features.py` `word_reminder` fills the same pieces into the AI's wording; its tokens (`[CLIENT]`, `[BILLS]`...) must stay in step with `reminder_skeleton` |
| an entity's `form_fields` or `private_columns` | `ai/features.fillable_fields` decides from them what a model may be asked to fill; a new private column must be in `private_columns` or it could be offered |
| the document categories (`documents.CATEGORIES`) or the letter tags `letterhead.clean_html` allows | the AI's suggested kind is checked against the categories; a letter written by the AI is rebuilt through `clean_html` |

### Navigation and pages

| If you add | Also change |
|---|---|
| a page inside an existing workspace | `frontend/src/workspaceRoutes.tsx`, made with `lazyPage(() => import('./pages/X'), 'X')` (never a plain `import` of a page: it would put the page back in the start-up download; `npm run check:bundle` notices) |
| a library that only some pages use (charts, an editor, a PDF tool) | import it only from those pages, never from the shell, `Layout`, `App`, the Copilot panel or a context; if the Copilot needs it, load that part lazily as `assistant/ChartBlock.tsx` is. Add it to `vendorChunk` in `vite.config.ts` if it is large and rarely changes |
| a file under `frontend/dist/assets` or how `dist` is served | `backend/app/frontend_serving.py` (cache rules rest on the hash in the file name), `test_frontend_serving.py` |
| a new workspace (a new first path segment) | `App.tsx` (the protected `/<segment>/*` placeholder), `WorkspacePanes.tsx` (`SectionId`, `PANE_CLASS`, `TREES`, `matchSection`), `workspaceRoutes.tsx`, `ProtectedRoute.tsx`, and `can_access_page` / `ROLE_PAGES` in `backend/app/auth.py` if it has its own page permission |
| a rail item | `NAV_GROUPS` in `components/Layout.tsx`, and `NavArea`, `DEFAULTS` and `areaOf` in `context/TabMemoryContext.tsx` |

Workspaces stay mounted after the first visit. A page that loads data should depend on `generation` from
`DataRefreshContext` so the top-bar refresh reloads it.

### Schema files and startup

| If you add or rename | Also change | Caught by a test |
|---|---|---|
| a `.sql` file in `.cursor/db/` | the file list in `scripts/init_db_windows.ps1` **and** `scripts/init_db_mac.sh` | Yes |
| a `.sql` file that existing databases need | its path in `entities.SQL_MIGRATIONS` (after the files it depends on). That list is what `python -m app.migrate` runs, in the deploy and at API start | Yes: a file in the init scripts that is neither in the list nor a known legacy file fails `test_migrate.py` |
| a file applied at startup | the path constant in `entities.py`, `dw_sync.py`, `tally_ods.py` or `tally_dw.py` | Yes: the file must exist |
| a step in `scripts/deploy.ps1` | the order is a contract (dump and migration before the old server stops; rollback after the checkout; the version comes from git, not the record). Change `test_deploy_tools.py` with it, and rehearse in a throwaway clone with a broken migration and a server that will not start | Partly: order, rollback and resume are pinned; a real run is not |
| a column or key in `/api/health/ready`, `/api/health/version` or `data/release.json` | `deploy_tools.smoke` (reads them), `health.py`, `types.ts` `SystemHealth`. `/api/health` must stay exactly `{"status":"ok"}` | Yes |
| a rule the database holds about a value (`migrate_data_rules.sql`) | the same rule in `entities.invalid_reason` or a `field_rules` entry (so the person is told before the save), and the message in `entity_service.CONSTRAINT_MESSAGES` keyed by the constraint's name; `test_integrity_fixes.py` checks every message has its constraint | Yes |

Order matters: `migrate_case_transaction_bill.sql` needs the table `migrate_bill.sql` creates.

### Settings, ports and packages

| If you change | Also change |
|---|---|
| add an `ORION_*` setting | `.env.example`, `deploy/env.prod.example`, and the real `.env` on each machine by hand (it is not in git) |
| a port (8000 API dev, 5173 UI dev, 8100 prod) | `frontend/vite.config.ts`, CORS in `security_headers.cors_options` (and `ORION_CORS_ORIGINS` for a prod address), `scripts/start-*.ps1` and `.sh`, `scripts/deploy.ps1`, `desktop/app.py`, `desktop/prod_app.py`, the guides |
| an endpoint that creates a bill, records money, or sends something to a client | take an `Idempotency-Key` and claim it inside the transaction that does the work (`Idempotency.claim`, then `remember` before the commit, as `create_bill`, `update_bill` and `record_payment` do), pass it from the page with `newIdempotencyKey()` kept for the life of the form, and guard a second click with a ref, not only a state flag. `test_idempotency.py` pins the order |
| a call in `api/client.ts` that passes its own `headers` | `request()` merges them after `...options`; spreading options last once replaced all the headers and dropped `Content-Type`. A test pins it |
| a new way to reach the database, a new `SET`, advisory lock, temp table, `LISTEN` or autocommit, or work that holds a connection while it waits on something slow | use `db_cursor()` / `get_connection()`; the pool resets a returned connection by rolling back, nothing else, so session state would leak to the next borrower: use `raw_connection()` for it. Never hold a pooled connection across a call to Tally or an AI provider. `test_db_pool.py` fails on a new `psycopg2.connect` that is not listed |
| a new log line, a new background job, or a new `except Exception` | use `logging.getLogger(__name__)`, never `print`; never put a query string, token, password, cookie or body in a message; an `except` re-raises or logs; a condition that is normal on a machine is DEBUG, not WARNING (the System page counts errors). A job's result belongs in its own table (`etl_run`, `backup_run`): `health.py` reads those. `test_observability.py` fails on a `print` and on the handlers it lists |
| a new public route that must stay up when the database is down, or a change to `/api/health` | `/api/health` is polled by `desktop/app.py` and `desktop/prod_app.py` and must keep returning `{"status":"ok"}`; `/api/health/ready` is the one that checks the database |
| a chart that sizes itself to its container (`height="100%"`), or a card that hosts `CategoryBar` | it must sit inside `Fill` (`CategoryBar.tsx`), which draws it out of the flow; a card that should let it take the room left is a flex column. Test at 125% and 150% zoom (display scaling), not just 100%: a loop between the chart and its box settles at whole pixels and runs away at fractional ones. `test_chart_layout.py` pins the source |
| a script, font, image, frame or API call from a new place, or an inline `<script>` or `style` block in `index.html` | `build_csp` in `security_headers.py` (the production page refuses anything it does not list: a missing font, a blank preview or a dead feature shows only in the browser console, "Refused to ..."); inline scripts go in `frontend/public/`. `test_security_headers.py` scans the frontend; the real check is the production build in a browser (`ORION_SERVE_FRONTEND=1`) with `ORION_CSP=report-only` |
| the cookie, or how the site is reached (a new address, the Tailscale proxy, HTTPS) | `cookie_secure` and `ORION_COOKIE_SECURE` in `security_headers.py`; set and clear the cookie with the same attributes (`auth_router.login` and `logout`) |
| a way to change a person's password or active state, or anything else that should sign them out | call `sessions.revoke_all(user_id, reason, cur=cur)` in the same transaction (`auth.update_user_password`, `complete_password_reset` and `set_user_active` do); `test_sessions_and_throttle.py` fails a change that drops it |
| a door that can be knocked on without signing in (login, reset, registration, anything new) | `_limited(kind, ...)` and `throttle.record(...)` in the route, and a rule for the kind in `throttle.RULES` with a message in `MESSAGES`; the test lists the doors |
| the sign-in cookie or how a request becomes a user | `sessions.py` (`user_for_token`), `dependencies.py`, the chat socket (`messages_router._socket_user`); never read the cookie anywhere else |
| a Python package | pin it in `backend/requirements.txt` (`==`), then refresh `backend/constraints.txt` from an empty virtualenv (DEVELOPMENT.md, "Dependencies"). Every install passes `-c backend/constraints.txt`; a new install script must too. `test_supply_chain.py` fails on a loose pin, a lock that disagrees, or an install without the lock |
| a check CI runs, or a new kind of check | `.github/workflows/ci.yml`; the job names `backend`, `frontend` and `dependency-audit` are what branch protection requires, so renaming one un-requires it. CI has no database: a test that needs one must skip unless its flag is set |
| a setting that must be private in production, or a development default | `config.py` (the `DEV_*` constants), `startup_checks.py` (what production refuses), `deploy/env.prod.example`, `.env.example`, `test_startup_checks.py` |
| a frontend package | `frontend/package.json` and `package-lock.json`. `deploy.ps1` runs the build |

### The two interfaces (Classic and Lumen)

| If you change | Also change |
|---|---|
| the list of areas, their names, icons or who sees them | `components/nav/navigation.ts` only: both the classic rail and Lumen's dock, launcher and Today page read it. A new area also needs its hue and blurb there (`AREA_HUE`, `AREA_BLURB`), and the usual `TabMemoryContext`, `WorkspacePanes`, route and `App.tsx` entries |
| a page or a shared component | it must look right in both interfaces: use the tokens and shared classes only (never a colour or a size of its own), and put anything specific to Lumen in `lumen.css` under `html[data-experience='lumen']`, never in the component |
| the top bar, the bells, the account menu | there are two: the classic one in `Layout.tsx` and `components/lumen/LumenTopBar.tsx` (its own account menu and the + menu). A new bell or button goes in both |
| what a signed-in person sees at `/` | `pages/LumenHome.tsx` (Lumen) and the company page `HomePage.tsx` (signed out, and Classic); `HomeSwitch.tsx` chooses |
| a saved appearance setting | `AppearancePrefs`, `sanitize`, `DEFAULT_PREFS`, `backend/app/appearance.py` (`clean_appearance`; the whole value must stay under 1,024 bytes) and `test_appearance.py` |
| a Lumen theme or palette | one object in `theme/themes.ts` with `experience: 'lumen'`; `npm run check:themes` checks its contrast like any other |
| a shared component that has a Lumen form (`DataTable`, `WorkbenchCatalog`, `EntityForm`, `MetricCard`, `IntentCard`, `FileTypeIcon` / `EntryIcon`, `ExcelUploadPanel`, `WriteGate`, `RecordHistoryModal`, the two bar charts) | change both forms together: the plain one and the Lumen one are in the same file or its `lumen/` partner (`cells.tsx`, `LumenCatalog.tsx`, `formParts.tsx`, `IconTile.tsx`, `DropZone.tsx`, `AnimatedFigure.tsx`). They must show the same data and offer the same actions. A new column kind or status word: `lumen/cells.tsx` and `scripts/check-lumen.mjs` |
| the size of a headline figure in Lumen | one rule in `lumen.css` (`.lumen-kpi .lumen-figure`): the card is a size container and the figure is `clamp(1.1rem, 8.5cqw, 1.9rem)` on one line, so every card in a row matches and a narrow card shrinks it. Never set a size class on such a figure (the rule wins); a figure that is really a list goes in `StatTile` rows (`lumen-kpi-rows`) |
| the Document Center screen (`DocumentCenterPage.tsx`, `ExplorerList`, `DocumentDrawer`, `UploadModal`) | each has a Lumen form chosen with `useLumen()` (the front door, step bar, chips, rows and floating selection bar are in `components/documents/lumenDocs.tsx`). They share one set of handlers: a new action goes into `menuItems` / `selectionTools` in the page so the right-click menu, the three-dots menu, the floating bar and the Classic toolbar all get it. The floating bar is rendered in a portal (the page is animated, so a fixed bar inside it would be fixed to the page). Typing in the front door's search swaps it for the results' search: keep `focusOnMount` |
| Attendance or Tenders screens (`AttendancePage`, `AttendanceSheetPage`, `TendersPage`, `BidFilters`) | each has a Lumen form chosen with `useLumen()` beside the plain one, over the same state and handlers (`components/attendance/lumenAttendance.tsx`, `pages/tenders/lumenTenders.tsx`): a new field on a register line or a new action on a bid goes into both. The register's Save and Post are in the floating `SheetBar` in Lumen and in the header in Classic, calling the same `save` / `startPosting`. Floating bars are rendered in a portal and sit above the phone tab bar |
| the Orion data front door, the bills register or the letters screens (`OrionDataPage`, `BillingPage`, `LettersPage`, `LetterEditorPage`) | each has a Lumen form chosen with `useLumen()` beside the plain one (`components/data/DataDesk.tsx`, `components/billing/LumenBillList.tsx`, `components/letterhead/lumenLetters.tsx`). A new record type that people add often goes in `THINGS_TO_DO` in `DataDesk.tsx` (its name must be the entity's name, and it is left out when the server does not list it); the data desk opens forms only through the same change warning and the `entity` / `mode=create` address `OperationalDataPage` reads. A new bill filter goes into `LumenBillList` and, if it should be in Classic too, `BillingPage` |
| a dashboard tab's charts, the brief (`DashboardBrief`, `Fold`, the `*Dashboard.tsx` pages) | in Lumen each tab's cards sit inside `<Fold keep={n}>` and only the first `n` are drawn until "Show more": a new chart goes after the ones that matter and `keep` is counted again; a card that must always be seen goes within `keep`. `Fold` goes directly inside the grid (its bar spans three columns); on the Overview tab it wraps whole `Section`s (`label` says what is behind it). The Tally pages are small and are not folded; their empty state tells "nothing loaded yet" (no billed data bounds) from "no match". `DashboardBrief` has a Lumen return beside the plain one over the same `lead`, `more`, `movers`, `steps` and handlers: a new action or finding kind goes into both |
| the monthly-billing screen (`DueToBillPage`, `LumenDue`, `billing.list_due_to_bill`) | the Lumen card list reads the same `cases` and the `billed` key (`{cases, total}`, month's Issued bills of cases not Inactive); change the due rule or that count and `test_clients.py` (`DueToBill`) and the plain table move with it. "About ₹" is the sum of the last bills of the cases still due, an estimate, never an amount to bill |
| the icon library and the start-up bundle (`vite.config.ts` `vendorChunk`) | icons are no longer a chunk of their own: a new import of `lucide-react` in the shell (`Layout`, contexts, the Copilot panel) adds to the 650 kB budget, a page's icons do not. `npm run check:bundle` says where it stands |
| what a client's page shows (`clients.py`, `ClientPage.tsx`) | the page reads, never writes: a new fact belongs in `clients.profile` (and `types.ts` `ClientProfile`), and money only inside `_money_block` and only for `auth.can_access_billing`. A new reader of what a client owes must use `receivables.client_statement`, not a sum of its own. A client has to be listed in `ClientsPage` and reachable from where its name is shown (Outstanding links to it) |
| what a case, employee or account page shows (`cases.py`, `employees.py`, `user_overview.py`, their pages) | read only: a new fact goes into the module's `profile`/`overview` and the type in `types.ts`. Money only inside `cases._money_block` and only for billing; pay only behind `can_access_bank`; never select a private employee column (`test_profiles.py` fails if the source names one). A new link from a name to its page (a case on a client page, a manager on an employee page) uses `/data/cases/CODE`, `/data/employees/CODE`, `/data/clients/CODE` |
| group chats (`chat_groups.py`, `chat.py` membership, `routers/messages_router.py` group routes, `ConversationList`, `ThreadView`, `GroupSection`) | **who is in a conversation is only ever asked of `chat._assert_member` / `_membership`** (the people other than the asker; for a group read from `chat_member` every time): a new route, socket event or query about a conversation must call it and send events to every id it returns (`other_ids`, never one `other_id`), and a new SQL that lists "my conversations" must include groups (`kind = 'group' AND EXISTS chat_member`). Lines nobody wrote are `chat_message.system`: every unread count, search and "new messages" marker excludes them, and `_message_chat.is_call` makes them uneditable. Calls and AI help use `_direct_peer` and are refused in a group. A new group action goes in `chat_groups.py` (the only writer of `chat_member`), then in the router as a `chat_changed` event to everyone left and `chat_deleted` to the person who is out. A message carries `sender_name` so a person who left is still named. `test_chat_integration.py` has the outsider matrix and a live-socket test for groups |
| calls (`calls.py`, `components/calls/`, the `call_*` events in `messages_router.py` and `ChatContext`) | the server and `useCallEngine` must agree on the events (`call_invite`, `call_accept`, `call_end`, `call_signal` from the browser; `call_started`, `call_ring`, `call_accepted`, `call_signal`, `call_ended`, `call_error` back; `CallEvent` in `ChatContext.tsx`) and on the set-up kinds (`calls.SIGNAL_KINDS`: offer, answer, candidate, state): a new kind goes in both, and `test_calls.py` is the contract on the server side. A call ends in `calls._finish`, the only place that writes the call's outcome and its line (`chat.add_call_message`): a new way a call can end goes there so the line, the unread count and both screens follow. The line is a `chat_message` with a `call_id`, so every reader of messages (previews in `messagePreview`, the list, search, pins, forward, edit, delete) must treat `call` lines as not editable; the checks are in `chat.py` (`is_call`). The microphone and camera are allowed only by `security_headers.PERMISSIONS_POLICY` (own pages): narrowing it breaks calls and voice notes. `CallHost` is lazy and mounted in `Layout`: keep it out of the start-up download (`check:bundle`) |
| voice notes (`RecorderBar`, `VoiceNote`, `chat_media.prepare_upload`, `chat.clean_waveform`) | audio is recognised by the content type the browser sends (`audio/...`) and kept as kind `audio` with `duration_ms` and `waveform`; the forward, shared-media (`kind=audio`) and inline-serving paths all know the kind: a new place that lists or serves attachments must handle it. The recorder picks webm/opus, mp4 or ogg by what the browser can record (`TYPES`) and the server's `AUDIO_EXTS` must accept each |
| the signed-out pages (`AuthFrame`, `LoginPage`, `ResetPasswordPage`) or the welcome tour (`WelcomeTour`, `components/welcome/events.ts`) | every signed-out page goes through `AuthFrame`, which has a Lumen form chosen with `useLumen()` beside the plain one: a new page there needs only a title, a subtitle and its form. `PasswordInput` (Caps Lock) and `PasswordStrength` are shared by sign-up, reset and any new password box. The tour's tiles come from the `can_*` flags of the signed-in user (`areasFor`): a new area with its own access flag should get a tile; `auth.public_user` must keep sending `created_timestamp` or the tour never opens by itself. The tour is lazy: keep it out of the start-up download (`check:bundle`) |
| the Admin users screen or Settings > Profile in Lumen (`AdminPage`, `components/admin/LumenPeople.tsx`, `SettingsPage`) | the cards read the same `users` and `signups` the table and the select did, and "Manage" only sets `selectedId` and opens the Manage tab, so a new action on a person goes in Manage (and the account page), not on the card. The access chips come from `LumenPeople.AREAS`: a new access flag in `ACCESS_FLAG_KEYS` should get a line there. The Lumen profile's single Save sends `display_name` and `email`/`phone` only when each changed, the same fields the two plain forms sent |
| the Messages screen (`MessagesPage`, `ConversationList`, `ThreadHeader`, `MessageBubble`, `Composer`, `ContactPanel` in `ThreadPanels`) | one design for both looks, drawn with the shared tokens; Lumen's extra skin is only in `lumen.css` (`chat-shell`, `chat-list`, `chat-row`, `chat-compose`, `chat-head`, `chat-call-button`, `chat-call-line`, `chat-hover-bar`, `chat-bubble`, `chat-bubble-mine`, `chat-bar`, `chat-composer`, `chat-send`): keep a hook when an element is rewritten. A new action on a conversation goes in the list row's menu, the header's options and the details drawer (`ContactPanel`) together; a new kind of message needs a glyph in `ConversationList.Glyph`, a preview in `messagePreview` and a form in `MessageBubble`. The list of everyone is hidden until the new-message button, a search or an empty inbox shows it (`showPeople`): a new way into a conversation must not rely on it being visible. Column widths: list 19.5 / 21 / 24rem at md / xl / 2xl, the details drawer lies over the thread below 2xl |
| Messages, My work or the task board in Lumen | Messages gets its Lumen look only from the `chat-*` class hooks (`chat-shell`, `chat-list`, `chat-row`, `chat-bubble`, `chat-bubble-mine`, `chat-composer`, `chat-input`, `chat-send`, `chat-head`) and their rules in `lumen.css`: keep a hook when its element is rewritten. My work's sentence and the task rows read the same counts and cards as the plain page |
| a money screen that has a Lumen layout (bill editor and view, Outstanding, TDS / GST / Credit notes tiles, the Bank tabs) | the plain layout and the Lumen one are in the same page, chosen with `useLumen()`; they must offer the same data and actions and call the same functions. The Lumen pieces are `components/billing/lumenBill.tsx`, `LumenReceivables.tsx`, `StatTile.tsx`, `components/bank/BalanceHero.tsx`, `lumenBank.tsx`; a new action or field on the page goes into both. The start-up bundle is 648 kB of 650 (`npm run check:bundle`): these load with their page, never in the shell |
| the dock's width or the space it leaves | `--lumen-dock-w`, `--lumen-dock-open` and `.lumen-main` in `lumen.css`, and `LumenDock.tsx` |

### Look and feel

| If you change | It affects |
|---|---|
| a token in `frontend/src/index.css` (`--orion-*`, `brand-*`, `alt-*`) | every screen, every theme. A value in the `:root` or `.dark` block must also change in `DEFAULT_LIGHT`/`DEFAULT_DARK` or the accent tokens in `theme/themes.ts` (the page shows the stylesheet before the script runs, then the engine's values): `npm run check:themes` fails if they differ |
| a new CSS variable the engine writes | add its default to `:root` (and `.dark` if it differs), map it in `@theme` if a Tailwind name is wanted, and set it in `resolveAppearance`. The check fails if `index.css` sets a variable the engine never does (constants are listed in `check-themes.mjs`) |
| a theme or a style (`theme/themes.ts`) | the settings screen, the quick menu and the previews read the list, so nothing else changes. Run `npm run check:themes`: it fails if any text, accent, status or button label falls under its contrast minimum in either mode |
| the accent / contrast rules (`theme/engine.ts`, `theme/color.ts`) | every theme and every custom accent. `check-themes.mjs` covers the seed colours and awkward accents (yellow, black, white) |
| what is saved (`AppearancePrefs` in `theme/types.ts`) | `sanitize` in `theme/preferences.ts` **and** `clean_appearance` in `backend/app/appearance.py` (and `test_appearance.py`), or the server will refuse or drop the new key |
| a colour in a component | don't: use a token. Raw Tailwind hues (`bg-amber-50`, `text-red-600`), `text-white` on a themed surface, `dark:` colour pairs and hex values break non-Default themes. Status: `text-warning bg-warning-dim`, `text-negative`, `text-positive`. Text on the rail: `text-rail-*`. Text on a photo: fixed white over an `ink` overlay, marked `data-photo` |
| a new overlay (dialog, menu, toast) | use `Modal`, `Drawer`, `Toast` or the `.overlay` class with `usePresence`, so it fades out and respects reduced motion; use `useDialog` for focus |
| `SERIES` / `CHART_COLORS` in `components/dashboard/format.ts` | every chart on both dashboard families |
| anything in `components/ui/` | every screen that uses it |
| `BillDocument.tsx` | the printed invoice, which customers see |

---

## Recipes

### Add a field to an existing record type

1. Add the column to the table's `CREATE TABLE` in `schema.sql`.
2. Add `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` to a file that runs at startup: extend one that already does
   (`migrate_opportunity_fields.sql`, `migrate_bill.sql`, `migrate_case_transaction_bill.sql`), or add a new
   one (see "Add a schema file"). `schema.sql` alone is not enough, because it does not run at startup.
3. Add the field to `form_fields` in `entities.py`. The form, preview, Excel template and upload follow.
4. Add it to the entity's spec in `dw_sync.py` and to its table in `dw_schema.sql` (both the `CREATE TABLE` and
   an `ADD COLUMN IF NOT EXISTS`).
5. If a dashboard should filter or measure by it, add it in `dashboard/filters.py` / `views.py`.
6. Update `data-model.md`. Run the tests. Restart the dev API twice and read its log.

### Rename or remove a field

Search the whole repo for the column name first: `entities.py`, `dw_sync.py`, `dashboard/`, `billing.py`,
`.cursor/db/`, `frontend/src/`. Do not drop or rename the column in the same release that stops using it: stop
using it, release, then remove it in a later release. A rollback restores old code against the new schema.

### Add a new record type

Table, sequence and `next_code` default in `schema.sql`; `created_by` and `last_updated_by` (add the table to
`migrate_audit.sql`); a startup file for existing databases; an `ENTITIES`
entry; `MERGE_KEYS`; the name in `DATASET_GROUPS`; a spec in `dw_sync.py` plus `REFRESH_ORDER`; tables in
`dw_schema.sql`; `data-model.md`. The contract tests fail until the catalog and the warehouse know about it.

### Add something the Copilot can do

1. Write a function in the right file under `backend/app/ai/tools/` and register it with `@tool(...)`. Reuse the
   application's own service for the work; never query tables the screens do not.
2. Give it `needs=` the same permission the screen needs. If it changes anything, set `kind=WRITE`, `confirm=True`,
   `risk=` and a `prepare` that returns the confirmation card (title, rows, warning) from the validated arguments.
3. Return `ToolResult(data, summary)`. Put numbers the model may quote in `data`; register anything to draw with
   `ctx.block(...)` and list it under `"blocks"` so the model can place it.
4. If it is something people will ask for in plain words, add a pattern to `routing/intents.py` and wording to `routing/compose.py`, so Orion can answer
   it with no model. Run `pytest backend/tests/test_ai.py backend/tests/test_ai_routing.py` and look at the screen (`ORION_AI_LOCAL_PROVIDER=scripted` gives a model-shaped stand-in).

### Add a schema file

Create `migrate_<name>.sql` with re-runnable statements. Add it to both init scripts and to `SQL_MIGRATIONS` in `entities.py`
(the runner in `migrate.py` applies it, records it and falls back to the superuser; nothing else needs calling). Start the dev API
twice and run `python -m app.migrate --status`: the new step says `applied`.

### Add a schema, or a table in one of the four schemas

Backups dump `orion_ods`, `orion_dw`, `tally_ods` and `tally_dw` (`backup.SCHEMAS`). A new table in one of them is
included automatically, as long as the `orion_backup` role can read it: `deploy/create_backup_role.sql` sets default
privileges for tables created by `orion_user` and `postgres`, so a table made by any other role would be missed. A
**new schema** must be added to `backup.SCHEMAS`, to the grants in `create_backup_role.sql` (re-run it on prod) and to the
fingerprint, or it is not backed up. A dump that lacks a schema is rejected and the backup fails.

### Add a chart, KPI or table to an Orion dashboard

Add the block to the view's builder in `dashboard/views.py` or `views_ops.py` with a new id; read it by that exact id in
the page under `pages/dashboards/`. Read from `orion_dw` through a scope in `dashboard/filters.py`, never `orion_ods`. For a
KPI, add it to `engine.Dash.kpis`, its help to `kpi_help.py`, its key to the tab's `kpiKeys` and to `kpiIcons.tsx`. Use a colour
from `SERIES`. If the chart should open the rows behind it, give its `ChartCard` a `records` prop. Check the view with a
filter applied and with an empty date range. A new warehouse column a dashboard needs must exist in `dw_schema.sql` and
`dw_sync.py` first (see "A column in an orion_ods business table").

### Add an API route and a screen for it

Route with a permission dependency in the right router; logic in a module, not in the router; a function in
`api/client.ts`; types in `types.ts`; the page under `pages/`; its route in `workspaceRoutes.tsx`; a rail item
only if it is a new destination.

### Change something about bills

Read the Billing section of [features.md](features.md) first. Keep its rules, keep `billing.py` and
`billCalc.ts` in step, and run `test_billing.py`: it holds real invoices that must still add up.

---

## What no test protects

Know these are unguarded, and check them by hand:

- A column added to a table but forgotten in the warehouse spec, a dashboard, or the data model.
- Dashboard block ids and KPI keys between `views.py` and the pages.
- A dropdown's `options` against the table's `CHECK` constraint.
- That a new SQL file is called at startup (only its presence in the init scripts is tested).
- Any behaviour that needs a database: saving a record, a warehouse load, a bill's revenue rows. These were
  checked by hand against a scratch database when written; there is no automated database test.
- Everything on the Tally side beyond the pure helpers.
- The frontend's behaviour. `tsc` and the build check types, not what a screen does.
