-- willow-data-vault / schema / receipts (append-only tool-call ledger)
-- Backend: SQLite. Owned by willow. Extracted verbatim from willow-mcp receipts.py.
--
-- One row per tool call: who (app_id), what (tool), how it went (outcome), and
-- an optional detail. This is the local activity trail — sensitive, and it stays
-- in the box. (Distinct from the willow-gate PGP check-in ledger, which lives
-- under ledgers/.)

CREATE TABLE IF NOT EXISTS receipts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    app_id  TEXT NOT NULL,
    tool    TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail  TEXT
);
CREATE INDEX IF NOT EXISTS idx_receipts_ts     ON receipts(ts DESC);
CREATE INDEX IF NOT EXISTS idx_receipts_app_id ON receipts(app_id);
