#!/usr/bin/env bash
# provision.sh — stand up an EMPTY willow data-vault box from this blueprint.
#
# The blueprint (this repo) is schema + structure. This script provisions a
# populated-but-empty BOX at a path you choose. The box holds real data and the
# crypto key; it is NEVER committed back (see the repo .gitignore).
#
# Usage:
#   bootstrap/provision.sh /path/to/box
#
# What it does (idempotent):
#   1. create the box directory layout
#   2. apply the owned SQLite schemas (secrets, SOIL, receipts, Kart tasks)
#   3. generate the Fernet vault.key (0600) if absent — the crypto linchpin
#   4. print the next steps (point WILLOW_HOME / WILLOW_STORE_ROOT at the box;
#      run willow-mcp-init for the config/mcp_apps/personas structure)
#
# It does NOT: create the Postgres KB (adaptive — see schema/05_knowledge.reference.sql),
# populate any data, or install apps. Blueprint stands up the box; nothing more.

set -euo pipefail

BOX="${1:?usage: provision.sh /path/to/box}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SCHEMA="$HERE/schema"

echo "==> provisioning willow data-vault box at: $BOX"
mkdir -p "$BOX"/{db,config,mcp_apps,ledgers}
chmod 700 "$BOX"

# Apply a schema to a SQLite DB. Prefer the sqlite3 CLI; fall back to Python's
# stdlib sqlite3 so the blueprint works without the CLI installed.
if command -v sqlite3 >/dev/null 2>&1; then
  _apply() { sqlite3 "$1" < "$2"; }
elif command -v python3 >/dev/null 2>&1; then
  _apply() { python3 -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.executescript(open(sys.argv[2]).read()); c.close()' "$1" "$2"; }
else
  _apply() { echo "    !! no sqlite3 CLI and no python3 — apply schema/*.sql yourself"; return 1; }
fi

apply() {  # apply <sqlite-db> <ddl-file>
  local db="$BOX/db/$1" ddl="$SCHEMA/$2"
  echo "    schema: $2 -> db/$1"
  _apply "$db" "$ddl" && chmod 600 "$db"
}

apply vault.db    01_secrets.sql
apply soil.db     02_soil_records.sql
apply receipts.db 03_receipts.sql
apply kart.db     04_tasks.sqlite.sql

# The crypto linchpin: the Fernet key. Generated locally, 0600, never git.
# Best-effort and NON-FATAL: if cryptography is missing or broken, willow-mcp's
# Vault.init() creates the key on first run. Never abort provisioning over it.
KEY="$BOX/vault.key"
if [ -f "$KEY" ]; then
  echo "    vault.key already present — left untouched"
elif python3 -c "from cryptography.fernet import Fernet; open('$KEY','wb').write(Fernet.generate_key())" 2>/dev/null; then
  chmod 600 "$KEY"
  echo "    generated vault.key (0600) — the crypto root; NEVER commit or copy it"
else
  echo "    note: could not generate vault.key here (cryptography unavailable);"
  echo "          willow-mcp's Vault.init() will create it (0600) on first run."
fi

cat <<EOF

==> box provisioned (empty). Next:
    export WILLOW_HOME="$BOX"
    export WILLOW_STORE_ROOT="$BOX"     # Kart queue + stores resolve here
    willow-mcp-init                      # lays down config/mcp_apps/personas/skills
    # Postgres KB is adaptive — see schema/05_knowledge.reference.sql

    This box holds data and the key. It must NEVER be committed to any repo.
EOF
