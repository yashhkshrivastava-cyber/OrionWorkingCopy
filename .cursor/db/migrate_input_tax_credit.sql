-- Input tax credit: the GST a supplier charged on a cost can be set against the GST Orion owes on its bills, but only with the supplier's GSTIN and
-- invoice number to claim it on. An expense now carries both. Optional in the database (an expense entered before this has neither); the form, the
-- Excel upload and the Copilot ask for them whenever an expense has GST (entities.invalid_reason). Safe to run again.

ALTER TABLE orion_ods.expense_transaction ADD COLUMN IF NOT EXISTS vendor_gstin TEXT;
ALTER TABLE orion_ods.expense_transaction ADD COLUMN IF NOT EXISTS vendor_invoice_no TEXT;

-- The GST position reads the expenses that carry credit, by month.
CREATE INDEX IF NOT EXISTS expense_transaction_itc_idx ON orion_ods.expense_transaction (transaction_date) WHERE vendor_gstin IS NOT NULL AND gst > 0;
