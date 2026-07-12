-- willow-data-vault / schema / Knowledge base (Postgres) — REFERENCE ONLY
-- Backend: Postgres. NOT owned by willow — willow ADAPTS to your existing
-- `knowledge` table rather than creating one.
--
-- ⚠ Do NOT treat this as canonical DDL. willow-mcp resolves columns at runtime
-- via schema_profile.py (e.g. "content" → content|body|text, "source" →
-- source_type|origin|origin_ref) and writes with dynamic
-- `INSERT INTO knowledge ({cols})`. Hardcoding a shape here — or assuming this
-- one — is exactly what caused the UndefinedColumn crashes documented in
-- willow-mcp/docs/design/schema-adaptation.md.
--
-- Use this ONLY to stand up a knowledge table on a FRESH box that has none.
-- Against any pre-existing KB, leave the table as-is and confirm the mapping:
--     schema_confirm_mapping(app_id=..., table="knowledge")

CREATE TABLE IF NOT EXISTS knowledge (
    id         bigserial PRIMARY KEY,
    content    text NOT NULL,          -- the knowledge payload (a.k.a. body/text)
    source     text,                   -- provenance (a.k.a. source_type/origin)
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_created ON knowledge (created_at DESC);
-- Full-text search is expected by knowledge_search; add per your PG setup, e.g.:
-- CREATE INDEX idx_knowledge_fts ON knowledge USING gin (to_tsvector('english', content));
