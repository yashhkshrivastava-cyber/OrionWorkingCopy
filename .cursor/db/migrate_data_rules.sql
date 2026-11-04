-- Rules about the values of a record that the database holds itself, so every way of writing one (the forms, the Excel
-- upload, the Copilot) meets them, not only the one that remembered to check.
-- Idempotent: safe on existing databases, and applied on every API start.
--
-- The constraints are NOT VALID: rows already stored are not checked (and so cannot stop this script), and every row that is
-- inserted or changed from now on is. The loop checks are triggers, because a loop is a property of a chain of rows.
--
--   * kilometres and readings are never negative, and a car's final reading is never below its initial reading;
--   * an employee is never their own manager, and manager chains never loop;
--   * a client's group chain never loops (a client is never its own group: migrate_client_group.sql).
--
-- The constraint names are what app/entity_service.py turns into a message, so keep them in step.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'case_monthly_allowed_km_not_negative' AND conrelid = 'orion_ods."case"'::regclass) THEN
        ALTER TABLE orion_ods."case"
            ADD CONSTRAINT case_monthly_allowed_km_not_negative CHECK (monthly_allowed_km IS NULL OR monthly_allowed_km >= 0) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'car_per_km_price_not_negative' AND conrelid = 'orion_ods.car'::regclass) THEN
        ALTER TABLE orion_ods.car
            ADD CONSTRAINT car_per_km_price_not_negative CHECK (per_km_price IS NULL OR per_km_price >= 0) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'car_transaction_readings_not_negative' AND conrelid = 'orion_ods.car_transaction'::regclass) THEN
        ALTER TABLE orion_ods.car_transaction
            ADD CONSTRAINT car_transaction_readings_not_negative
            CHECK ((initial_reading IS NULL OR initial_reading >= 0) AND (final_reading IS NULL OR final_reading >= 0)) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'car_transaction_final_not_below_initial' AND conrelid = 'orion_ods.car_transaction'::regclass) THEN
        ALTER TABLE orion_ods.car_transaction
            ADD CONSTRAINT car_transaction_final_not_below_initial
            CHECK (initial_reading IS NULL OR final_reading IS NULL OR final_reading >= initial_reading) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'car_transaction_driven_km_not_negative' AND conrelid = 'orion_ods.car_transaction'::regclass) THEN
        ALTER TABLE orion_ods.car_transaction
            ADD CONSTRAINT car_transaction_driven_km_not_negative CHECK (driven_km IS NULL OR driven_km >= 0) NOT VALID;
    END IF;
END $$;

-- Money received is recorded on its bill. A revenue entry that is Committed (received) must belong to a bill, so a receipt cannot be put straight into the
-- bank balance through a form, an Excel upload or the Copilot, bypassing the billing controls (numbering, idempotency, the GST and payment rules). Money with
-- no bill (an advance, a deposit) is a Bank entry. Only what is NEW is refused: an insert, or an update that makes a row Committed without a bill, or takes a
-- Committed row off its bill. A Committed entry with no bill that was stored before this rule can still be corrected where it stands, so no balance moves.
-- The constraint name is what app/entity_service.py turns into a message (CONSTRAINT_MESSAGES), so keep them in step.
CREATE OR REPLACE FUNCTION orion_ods.case_transaction_committed_needs_bill() RETURNS trigger AS $$
BEGIN
    IF NEW.transaction_status = 'Committed' AND NEW.bill_code IS NULL
       AND (TG_OP = 'INSERT' OR OLD.transaction_status IS DISTINCT FROM 'Committed' OR OLD.bill_code IS NOT NULL) THEN
        RAISE EXCEPTION 'Money received is recorded on its bill'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'case_transaction_committed_needs_bill';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS case_transaction_committed_needs_bill ON orion_ods.case_transaction;
CREATE TRIGGER case_transaction_committed_needs_bill
    BEFORE INSERT OR UPDATE ON orion_ods.case_transaction
    FOR EACH ROW EXECUTE FUNCTION orion_ods.case_transaction_committed_needs_bill();

-- An employee's manager chain never comes back to the employee (which also makes an employee their own manager impossible).
CREATE OR REPLACE FUNCTION orion_ods.refuse_employee_manager_loop() RETURNS trigger AS $$
DECLARE
    walker TEXT := NEW.manager_code;
    hops   INTEGER := 0;
BEGIN
    IF walker IS NOT NULL AND walker = NEW.employee_code THEN
        RAISE EXCEPTION 'An employee cannot be their own manager'
            USING ERRCODE = '23514', CONSTRAINT = 'employee_manager_not_self';
    END IF;
    WHILE walker IS NOT NULL AND hops < 200 LOOP
        IF walker = NEW.employee_code THEN
            RAISE EXCEPTION 'That manager already reports, directly or not, to this employee'
                USING ERRCODE = '23514', CONSTRAINT = 'employee_manager_no_loop';
        END IF;
        SELECT manager_code INTO walker FROM orion_ods.employee WHERE employee_code = walker;
        hops := hops + 1;
    END LOOP;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- A client's group chain never comes back to the client.
CREATE OR REPLACE FUNCTION orion_ods.refuse_client_group_loop() RETURNS trigger AS $$
DECLARE
    walker TEXT := NEW.client_group_code;
    hops   INTEGER := 0;
BEGIN
    WHILE walker IS NOT NULL AND hops < 200 LOOP
        IF walker = NEW.client_code THEN
            RAISE EXCEPTION 'That group already belongs, directly or not, to this client'
                USING ERRCODE = '23514', CONSTRAINT = 'client_group_no_loop';
        END IF;
        SELECT client_group_code INTO walker FROM orion_ods.client WHERE client_code = walker;
        hops := hops + 1;
    END LOOP;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- Only a row whose manager or group is being set or changed is checked, so a loop that is already stored does not stop
-- an unrelated edit of one of its rows.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'employee_manager_loop_check' AND NOT tgisinternal) THEN
        CREATE TRIGGER employee_manager_loop_check
            BEFORE INSERT OR UPDATE OF manager_code ON orion_ods.employee
            FOR EACH ROW EXECUTE FUNCTION orion_ods.refuse_employee_manager_loop();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'client_group_loop_check' AND NOT tgisinternal) THEN
        CREATE TRIGGER client_group_loop_check
            BEFORE INSERT OR UPDATE OF client_group_code ON orion_ods.client
            FOR EACH ROW EXECUTE FUNCTION orion_ods.refuse_client_group_loop();
    END IF;
END $$;
