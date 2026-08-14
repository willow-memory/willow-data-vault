-- willow-data-vault / schema / receipts (append-only tool-call ledger)
-- Backend: SQLite. Owned by willow. Base five columns (id, ts, app_id, tool,
-- outcome, detail) extracted verbatim from willow-mcp receipts.py.
--
-- One row per tool call: who (app_id), what (tool), how it went (outcome), and
-- an optional detail. This is the local activity trail — sensitive, and it stays
-- in the box. (Distinct from the willow-gate PGP check-in ledger, which lives
-- under ledgers/.)
--
-- ── Tamper-evidence (give-back, this change) ────────────────────────────────
-- prev_hash / hash are a hash chain over the row stream, pattern-ported from
-- Nestor's hash-chained ledger (nestor/ledger.py, Apache-2.0,
-- github.com/rudi193-cmd/Nestor, pinned v0.2.0) — same shape as that file's
-- prev-is-sha256-of-the-previous-entry chain, reimplemented here for a SQL
-- table instead of a JSONL file. No Nestor code is copied verbatim; the
-- pattern is re-expressed in this repo's own idiom. Verified by
-- bootstrap/verify_receipts.py — see that file for the exact canonical-form
-- and hashing rules the chain depends on. A broken chain there is a
-- REFUSAL (nonzero exit), never a warning, matching nestor.ledger.verify's
-- contract.
--
--   prev_hash  the `hash` of the row immediately before this one, ordered by
--              id ascending. The first row in the table carries the literal
--              string 'genesis' — the same empty-chain sentinel
--              nestor.ledger.head()/verify() use.
--   hash       SHA-256 hex digest of this row's own canonical JSON form:
--                {"id": <id>, "ts": <ts>, "app_id": <app_id>, "tool": <tool>,
--                 "outcome": <outcome>, "detail": <detail>,
--                 "prev_hash": <prev_hash>}
--              serialized with Python's json.dumps default separators
--              (", " / ": "), ensure_ascii=False, in exactly that key order.
--
-- Editing any past row's stored columns changes what its `hash` *should* be
-- on re-hash, so the next row's `prev_hash` no longer matches — that mismatch
-- is what verify_receipts.py walks the table looking for.
--
-- Same limit Nestor's ledger states up front: the walk vouches for every row
-- *except the last*, which nothing follows yet. Keeping a separately-recorded
-- expected head (outside this box) closes that gap; this schema does not do
-- that on its own.
--
-- NOT (yet) wired: these two columns are NOT NULL, so willow-mcp's
-- receipts.py insert path must compute and supply them for every new row —
-- that writer-side patch lives in willow-mcp, out of scope for this
-- schema-and-bootstrap-only repo. Until it lands, this schema documents the
-- target shape; it does not by itself make any receipts.db chained. A box
-- provisioned before this change has a receipts table without these columns
-- — provision.sh does not attempt an in-place ALTER TABLE migration for that
-- case (SQLite's `CREATE TABLE IF NOT EXISTS` is a no-op against an existing
-- table), and verify_receipts.py reports that state explicitly rather than
-- mistaking "never chained" for "tampered".

CREATE TABLE IF NOT EXISTS receipts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    app_id    TEXT NOT NULL,
    tool      TEXT NOT NULL,
    outcome   TEXT NOT NULL,
    detail    TEXT,
    prev_hash TEXT NOT NULL,
    hash      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_receipts_ts     ON receipts(ts DESC);
CREATE INDEX IF NOT EXISTS idx_receipts_app_id ON receipts(app_id);
