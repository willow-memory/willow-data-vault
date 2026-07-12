-- willow-data-vault / schema / SOIL store (local key/value with soft-delete)
-- Backend: SQLite. Owned by willow. Extracted verbatim from willow-mcp db.py.
--
-- The SOIL store is willow's local KV substrate. `data` is the record payload;
-- `deviation`/`action` drive willow's work_quiet/flag/stop signalling. Rows are
-- soft-deleted (deleted=1), never dropped — matching archive-don't-delete.

CREATE TABLE IF NOT EXISTS records (
    id         TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deviation  REAL NOT NULL DEFAULT 0.0,
    action     TEXT NOT NULL DEFAULT 'work_quiet',
    deleted    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_deleted ON records(deleted);
