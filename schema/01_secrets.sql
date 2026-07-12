-- willow-data-vault / schema / secrets (Fernet-encrypted secret store)
-- Backend: SQLite. Owned by willow. Extracted verbatim from willow-mcp vault.py.
--
-- The `value` column holds a Fernet ciphertext. It is meaningless without the
-- box's vault.key (0600, NEVER committed). That key is the crypto root of the
-- vault's "agents cannot carry it out" guarantee: copy this DB without the key
-- and every secret is unreadable.

CREATE TABLE IF NOT EXISTS secrets (
    name  TEXT PRIMARY KEY,
    value BLOB NOT NULL
);
