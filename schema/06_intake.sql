-- 06_intake.sql — the vault's content index and intake log (SQLite)
--
-- OWNED BY THIS REPO. Nothing upstream defines these tables; they exist so a
-- box can answer one question cheaply and correctly:
--
--     "do I already hold this file?"
--
-- The question is harder than it looks, and the wrong answer is expensive in
-- both directions. Answering by FILENAME re-files things the box already has
-- under a different name, and misses things it holds inside an archive. A live
-- example, 2026-09-01: a name-based `find` over a populated box reported
-- conversations.json / memories.json / users.json as absent. All three were
-- present, inside knowledge-extractions.tar.gz under
-- personal/knowledge/claude-ai-exports/. Name lookup cannot see into a tarball,
-- so it reported "absent" for a file the box had held for months.
--
-- So identity here is the SHA-256 of the bytes, never the path, and archive
-- MEMBERS are indexed as first-class rows. A file is "in the vault" if its
-- digest is present, whether it sits loose on disk or inside a tar/zip.
--
-- Covenant: this index records WHERE bytes are and WHAT they were called. It
-- makes no claim that anything in it is correct, current, verified, or
-- approved. It is a finding aid, not an authority — the same posture the
-- receipts chain takes (tamper-evidence, never a seal). Nothing here grants a
-- permission or ratifies a decision.
--
-- Written by bootstrap/vault_intake.py. Read by anything that wants to know
-- what the box holds — including other MCP servers, which is the point of
-- storing it as SQLite beside the box rather than in one tool's memory.

PRAGMA journal_mode = WAL;

-- ── every distinct byte-sequence the box holds ──────────────────────────────
CREATE TABLE IF NOT EXISTS vault_objects (
    sha256       TEXT NOT NULL,           -- identity. 64 lowercase hex.
    size         INTEGER NOT NULL,
    rel_path     TEXT NOT NULL,           -- path relative to the vault root
    container    TEXT,                    -- NULL if loose; else the archive's rel_path
    member_path  TEXT,                    -- NULL if loose; else path inside the archive
    mtime        REAL,
    indexed_at   TEXT NOT NULL,
    PRIMARY KEY (sha256, rel_path, member_path)
);

-- The same bytes may legitimately appear in several places (a loose copy and an
-- archived one). Lookup is by digest, so that is not a conflict — it is the
-- answer to "where are my copies".
CREATE INDEX IF NOT EXISTS idx_objects_sha    ON vault_objects (sha256);
CREATE INDEX IF NOT EXISTS idx_objects_path   ON vault_objects (rel_path);
CREATE INDEX IF NOT EXISTS idx_objects_member ON vault_objects (member_path);

-- ── tags, so other tools can select without parsing paths ───────────────────
-- Tags are DERIVED, not authored: a later run recomputes them. Anything a human
-- decides belongs in a record that survives recomputation, not here.
CREATE TABLE IF NOT EXISTS vault_tags (
    sha256  TEXT NOT NULL,
    tag     TEXT NOT NULL,
    source  TEXT NOT NULL DEFAULT 'derived',   -- derived | operator
    PRIMARY KEY (sha256, tag)
);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON vault_tags (tag);

-- ── what intake did, and why ────────────────────────────────────────────────
-- Append-only. A correction is a new row beside the old one, never an edit —
-- the same rule playgate's grant log follows.
-- run_id is not decoration. Without it a dry run and an apply leave rows of the
-- same shape, and a log read back later cannot tell "we considered filing this"
-- from "we filed it". Observed 2026-09-01: three dry runs plus one apply over
-- the same folder produced 356 rows that could not be separated by run.
CREATE TABLE IF NOT EXISTS vault_intake_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER,
    ts          TEXT NOT NULL,
    src_path    TEXT NOT NULL,
    sha256      TEXT,                     -- NULL only if the file was unreadable
    size        INTEGER,
    verdict     TEXT NOT NULL,            -- duplicate | new | name_conflict | unreadable
    action      TEXT NOT NULL,            -- reported | filed | skipped | refused
    dest        TEXT,                     -- rel_path it was filed to, when filed
    held_at     TEXT,                     -- for duplicate: where the box already had it
    note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_log_run     ON vault_intake_log (run_id);
CREATE INDEX IF NOT EXISTS idx_log_verdict ON vault_intake_log (verdict);
CREATE INDEX IF NOT EXISTS idx_log_sha     ON vault_intake_log (sha256);

-- ── a run, so a partial scan is legible as partial ──────────────────────────
CREATE TABLE IF NOT EXISTS vault_intake_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    vault_root    TEXT NOT NULL,
    source_root   TEXT,
    applied       INTEGER NOT NULL DEFAULT 0,   -- 0 = dry run
    objects_seen  INTEGER,
    archives_read INTEGER,
    archives_skipped INTEGER,                   -- over the size cap; recorded, not silent
    note          TEXT
);
