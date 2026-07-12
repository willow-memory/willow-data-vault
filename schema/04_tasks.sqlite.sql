-- willow-data-vault / schema / Kart task queue (SQLite backend)
-- Backend: SQLite. Owned by Kart (kartikeya). Extracted verbatim from
-- kartikeya queue.py (SqliteTaskQueue). Used when no Postgres is present.
--
-- A worker (kartikeya / WillowMcpTaskQueue) claims pending rows for its agent
-- and writes status/result/completed_at. See 04_tasks.postgres.sql for the
-- Postgres backend.

CREATE TABLE IF NOT EXISTS tasks (
    task_id      TEXT PRIMARY KEY,
    task         TEXT NOT NULL,
    agent        TEXT NOT NULL DEFAULT 'kart',
    submitted_by TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'pending',
    result       TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_claim ON tasks(status, agent);
