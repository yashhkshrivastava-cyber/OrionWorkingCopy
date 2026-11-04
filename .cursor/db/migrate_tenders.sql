-- Tenders (Tenders in the Utilities menu): saved searches for bids on the GeM portal, and the bids they found.
-- Idempotent: safe on existing databases, and applied on every API start.
--
-- Written only by app.tenders. Nothing here is loaded into the warehouse. A bid is GeM's public listing plus what Orion read
-- from its public bid document; nothing is ever sent to GeM.

-- Tenders is its own area, with a view flag and a change flag like Documents. The first time the pair is added, admins and
-- editors get both, which is what a new user of those roles gets by default; after that each person's access is set in Admin.
-- (The API also adds these columns at start, with the same backfill; this is for new databases.)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'orion_ods' AND table_name = 'app_user' AND column_name = 'tenders_access'
    ) THEN
        ALTER TABLE orion_ods.app_user
            ADD COLUMN IF NOT EXISTS tenders_access BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS tenders_write  BOOLEAN NOT NULL DEFAULT FALSE;
        UPDATE orion_ods.app_user
           SET tenders_access = role IN ('admin', 'editor'),
               tenders_write  = role IN ('admin', 'editor');
    END IF;
END $$;

-- What to look for: tender types (words matched against GeM's category, e.g. "security", "manpower outsourcing"), the cities the
-- work must be in, the kind of bid, and the estimated value. At least one tender type or one city.
CREATE TABLE IF NOT EXISTS orion_ods.tender_search (
    search_id              SERIAL PRIMARY KEY,
    name                   TEXT NOT NULL,
    tender_types           TEXT[] NOT NULL DEFAULT '{}',
    cities                 TEXT[] NOT NULL DEFAULT '{}',
    bid_kind               TEXT NOT NULL DEFAULT 'service',
    min_value              NUMERIC(16, 2) CHECK (min_value IS NULL OR min_value >= 0),
    max_value              NUMERIC(16, 2) CHECK (max_value IS NULL OR max_value >= 0),
    include_unpriced       BOOLEAN NOT NULL DEFAULT TRUE,
    is_active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_by             INTEGER,
    created_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT tender_search_has_something CHECK (cardinality(tender_types) > 0 OR cardinality(cities) > 0),
    CONSTRAINT tender_search_value_range CHECK (min_value IS NULL OR max_value IS NULL OR min_value <= max_value)
);

-- One bid on GeM, keyed by GeM's own id. The listing fields come with every search; the document fields once its bid document
-- has been read (document_status 'read'), or never when it could not be (document_status 'failed', with the reason).
CREATE TABLE IF NOT EXISTS orion_ods.tender_bid (
    bid_id                   BIGINT PRIMARY KEY,
    bid_number               TEXT NOT NULL,
    category                 TEXT,
    quantity                 INTEGER,
    ministry                 TEXT,
    department               TEXT,
    is_high_value            BOOLEAN,
    start_timestamp          TIMESTAMPTZ,
    end_timestamp            TIMESTAMPTZ,
    estimated_value          NUMERIC(16, 2),
    emd_amount               NUMERIC(16, 2),
    contract_period          TEXT,
    min_turnover             TEXT,
    experience_years         NUMERIC(5, 1),
    location_text            TEXT,
    location_districts       TEXT[] NOT NULL DEFAULT '{}',
    location_source          TEXT CHECK (location_source IN ('consignee', 'document')),
    document_status          TEXT NOT NULL DEFAULT 'pending' CHECK (document_status IN ('pending', 'read', 'failed')),
    document_error           TEXT,
    document_read_timestamp  TIMESTAMPTZ,
    first_seen_timestamp     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_timestamp      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- What a seller must put up to bid, from the document: the EMD and the performance guarantee (ePBG). GeM does not allow a tender
-- fee, so there is none to keep. reader_version says which version of Orion's reader read the document (an older one is read again).
ALTER TABLE orion_ods.tender_bid
    ADD COLUMN IF NOT EXISTS emd_required   BOOLEAN,
    ADD COLUMN IF NOT EXISTS epbg_required  BOOLEAN,
    ADD COLUMN IF NOT EXISTS epbg_percent   NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS epbg_months    INTEGER,
    ADD COLUMN IF NOT EXISTS reader_version INTEGER NOT NULL DEFAULT 1;
CREATE UNIQUE INDEX IF NOT EXISTS tender_bid_number_key ON orion_ods.tender_bid (bid_number);
CREATE INDEX IF NOT EXISTS tender_bid_end_idx ON orion_ods.tender_bid (end_timestamp);

-- A bid a search found, and what a person decided about it. Kept when the search is edited; removed with the search.
CREATE TABLE IF NOT EXISTS orion_ods.tender_match (
    search_id              INTEGER NOT NULL REFERENCES orion_ods.tender_search(search_id) ON DELETE CASCADE,
    bid_id                 BIGINT NOT NULL REFERENCES orion_ods.tender_bid(bid_id) ON DELETE CASCADE,
    matched_city           TEXT,
    location_confirmed     BOOLEAN NOT NULL DEFAULT FALSE,
    status                 TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'shortlisted', 'dismissed')),
    status_by              INTEGER,
    status_timestamp       TIMESTAMPTZ,
    first_matched_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (search_id, bid_id)
);
CREATE INDEX IF NOT EXISTS tender_match_bid_idx ON orion_ods.tender_match (bid_id);

-- One check of GeM (every active search), by the schedule or by a person. The System page reads the latest.
CREATE TABLE IF NOT EXISTS orion_ods.tender_run (
    run_id             SERIAL PRIMARY KEY,
    trigger            TEXT NOT NULL CHECK (trigger IN ('schedule', 'manual')),
    started_by         INTEGER,
    status             TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    started_timestamp  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_timestamp TIMESTAMPTZ,
    searches           INTEGER NOT NULL DEFAULT 0,
    requests           INTEGER NOT NULL DEFAULT 0,
    bids_seen          INTEGER NOT NULL DEFAULT 0,
    bids_new           INTEGER NOT NULL DEFAULT 0,
    documents_read     INTEGER NOT NULL DEFAULT 0,
    matches_new        INTEGER NOT NULL DEFAULT 0,
    note               TEXT,
    error              TEXT
);
CREATE INDEX IF NOT EXISTS tender_run_started_idx ON orion_ods.tender_run (started_timestamp DESC);
-- What a running check is doing now ("Asking GeM about Bhopal, page 12"), for the Tenders page; cleared when it ends.
ALTER TABLE orion_ods.tender_run ADD COLUMN IF NOT EXISTS progress TEXT;

-- Which bids each question to GeM (a city or a tender type, lower case, with the kind of bid) has returned. A later check asks
-- only until it reaches bids the question returned before, and a search is decided on everything its questions ever returned
-- that is still open, so a changed or new search sharing a question still sees the older bids.
CREATE TABLE IF NOT EXISTS orion_ods.tender_question_bid (
    question  TEXT NOT NULL,
    bid_kind  TEXT NOT NULL,
    bid_id    BIGINT NOT NULL REFERENCES orion_ods.tender_bid(bid_id) ON DELETE CASCADE,
    PRIMARY KEY (question, bid_kind, bid_id)
);
CREATE INDEX IF NOT EXISTS tender_question_bid_bid_idx ON orion_ods.tender_question_bid (bid_id);

-- How far back each question's list was last followed to its end (complete_from: the earliest publishing day covered; null when
-- a pass was cut short), so a later check can stop at known bids only once the whole window has been seen.
CREATE TABLE IF NOT EXISTS orion_ods.tender_question (
    question          TEXT NOT NULL,
    bid_kind          TEXT NOT NULL,
    complete_from     TIMESTAMPTZ,
    checked_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (question, bid_kind)
);
-- Which search a running check is on, for the Tenders page.
ALTER TABLE orion_ods.tender_run ADD COLUMN IF NOT EXISTS current_search_id INTEGER;

-- Two portals, kept apart: GeM ('gem') and MP Tenders ('mptenders', the Madhya Pradesh e-procurement portal). A search belongs to
-- one portal, and each portal has its own checks (tender_run.portal). A bid's source is its portal and its source_ref the portal's
-- own id (GeM's bid id; MP's Tender ID such as 2026_HED_543972_1). A GeM bid keeps GeM's id as its bid_id; a bid from another
-- portal takes one from tender_bid_local_seq, which starts far above GeM's ids.
ALTER TABLE orion_ods.tender_search ADD COLUMN IF NOT EXISTS portal TEXT NOT NULL DEFAULT 'gem';
ALTER TABLE orion_ods.tender_run ADD COLUMN IF NOT EXISTS portal TEXT NOT NULL DEFAULT 'gem';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tender_search_portal_ok') THEN
        ALTER TABLE orion_ods.tender_search ADD CONSTRAINT tender_search_portal_ok CHECK (portal IN ('gem', 'mptenders'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tender_run_portal_ok') THEN
        ALTER TABLE orion_ods.tender_run ADD CONSTRAINT tender_run_portal_ok CHECK (portal IN ('gem', 'mptenders'));
    END IF;
    -- The kind of bid: GeM has services and products; MP Tenders' Tender Category also has works.
    ALTER TABLE orion_ods.tender_search DROP CONSTRAINT IF EXISTS tender_search_bid_kind_check;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tender_search_bid_kind_ok') THEN
        ALTER TABLE orion_ods.tender_search ADD CONSTRAINT tender_search_bid_kind_ok
            CHECK (bid_kind IN ('all', 'service', 'product', 'works') AND (bid_kind <> 'works' OR portal = 'mptenders'));
    END IF;
END $$;

-- A database that had the short-lived list of portals per search (tender_search.sources, never released) is converted once: a
-- search on both portals becomes two, the MP one taking its MP bids with their statuses; then the list goes.
DO $$
DECLARE
    old_search RECORD;
    copy_id INTEGER;
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'orion_ods' AND table_name = 'tender_search' AND column_name = 'sources') THEN
        FOR old_search IN EXECUTE 'SELECT * FROM orion_ods.tender_search WHERE sources @> ''{gem,mptenders}''' LOOP
            INSERT INTO orion_ods.tender_search (name, tender_types, cities, bid_kind, min_value, max_value, include_unpriced, is_active,
                                                 created_by, portal)
            VALUES (old_search.name, old_search.tender_types, old_search.cities, old_search.bid_kind, old_search.min_value,
                    old_search.max_value, old_search.include_unpriced, old_search.is_active, old_search.created_by, 'mptenders')
            RETURNING search_id INTO copy_id;
            UPDATE orion_ods.tender_match m SET search_id = copy_id
              FROM orion_ods.tender_bid b
             WHERE b.bid_id = m.bid_id AND b.source = 'mptenders' AND m.search_id = old_search.search_id;
        END LOOP;
        EXECUTE 'UPDATE orion_ods.tender_search SET portal = ''mptenders'' WHERE sources = ''{mptenders}''';
        ALTER TABLE orion_ods.tender_search DROP CONSTRAINT IF EXISTS tender_search_sources_ok;
        ALTER TABLE orion_ods.tender_search DROP COLUMN sources;
    END IF;
END $$;
CREATE SEQUENCE IF NOT EXISTS orion_ods.tender_bid_local_seq START 1000000000000;
ALTER TABLE orion_ods.tender_bid
    ADD COLUMN IF NOT EXISTS source            TEXT NOT NULL DEFAULT 'gem',
    ADD COLUMN IF NOT EXISTS source_ref        TEXT,
    ADD COLUMN IF NOT EXISTS title             TEXT,
    ADD COLUMN IF NOT EXISTS reference         TEXT,
    ADD COLUMN IF NOT EXISTS work_description  TEXT,
    ADD COLUMN IF NOT EXISTS tender_category   TEXT,
    ADD COLUMN IF NOT EXISTS tender_fee        NUMERIC(16, 2),
    ADD COLUMN IF NOT EXISTS tender_fee_total  NUMERIC(16, 2),
    ADD COLUMN IF NOT EXISTS tender_fee_exempt BOOLEAN,
    ADD COLUMN IF NOT EXISTS emd_exempt        BOOLEAN;
UPDATE orion_ods.tender_bid SET source_ref = bid_id::TEXT WHERE source_ref IS NULL AND source = 'gem';
CREATE UNIQUE INDEX IF NOT EXISTS tender_bid_source_ref_key ON orion_ods.tender_bid (source, source_ref);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tender_bid_source_ok') THEN
        ALTER TABLE orion_ods.tender_bid ADD CONSTRAINT tender_bid_source_ok CHECK (source IN ('gem', 'mptenders'));
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orion_user') THEN
        GRANT ALL ON orion_ods.tender_search, orion_ods.tender_bid, orion_ods.tender_match, orion_ods.tender_run,
                     orion_ods.tender_question_bid, orion_ods.tender_question TO orion_user;
        GRANT ALL ON SEQUENCE orion_ods.tender_search_search_id_seq, orion_ods.tender_run_run_id_seq, orion_ods.tender_bid_local_seq
            TO orion_user;
    END IF;
END $$;
