# willow-data-vault

**The blueprint for willow's persistent, sovereign data box — schemas and
bootstrap only. Never data.**

This repo is how you *build* a willow data vault. It is not, and must never
become, the vault itself. The running vault (the "box") holds the knowledge
base, the databases, encrypted secrets, and any sensitive or user-specific
files. Those live locally and are **never committed here**.

> Repo = *how to build the box.* &nbsp; Box = *the populated instance that stays home.*

## Why this exists

willow runs as its own box. Separating that box's **data** from the replaceable
**app** and **compute** layers gives a three-layer architecture:

| Layer | What | Lifecycle |
|---|---|---|
| Compute / agents | the MCP server, the Kart sandbox, the agents | ephemeral, replaceable |
| Apps | `SAFE/apps/<app_id>/` — installed sovereign apps | replaceable payloads |
| **The vault (this)** | schemas · KB · DBs · secrets · user files | **persistent, sovereign** |

Agents operate **against** the vault in place but **cannot carry it out** —
enforced by three primitives that already exist in the stack:

- **gate `store_scope`** — an agent only ever sees its own collections.
- **kart bubblewrap** — a sandboxed task cannot reach host files.
- **consent** — sensitive/presence data never leaves the house.

The vault is simply the *named boundary* those three were already protecting.

## The crypto linchpin: `vault.key`

Secrets are stored as Fernet ciphertext in `vault.db`. They are meaningless
without `vault.key` (mode `0600`). That key is generated **locally**, lives only
in the box, and is **never committed** (see `.gitignore`). Copy the box's
`vault.db` without the key and every secret is unreadable — which turns "agents
can't carry it out" from a policy promise into a cryptographic one.

## What's in the blueprint

```
schema/
  01_secrets.sql             # Fernet secret store (SQLite)   — owned, verbatim
  02_soil_records.sql        # SOIL key/value store (SQLite)  — owned, verbatim
  03_receipts.sql            # tool-call ledger (SQLite)      — owned, verbatim
  04_tasks.sqlite.sql        # Kart task queue (SQLite)       — owned, verbatim
  04_tasks.postgres.sql      # Kart task queue (Postgres)     — owned, verbatim
  05_knowledge.reference.sql # KB (Postgres) — REFERENCE ONLY, willow ADAPTS
bootstrap/
  provision.sh               # stand up an empty box from the schemas
```

The four SQLite/Postgres task schemas are **owned** by willow/Kart and copied
verbatim from `willow-mcp` and `kartikeya`. The knowledge base is **not owned**:
willow adapts to whatever `knowledge` table already exists (columns resolved at
runtime by `schema_profile.py`), so `05_knowledge.reference.sql` is a reference
for a fresh box only — never assume its shape against an existing KB.

## Provision an empty box

```bash
bootstrap/provision.sh /path/to/box      # creates dirs, applies schemas, makes vault.key
export WILLOW_HOME=/path/to/box
export WILLOW_STORE_ROOT=/path/to/box    # Kart queue + stores resolve here
willow-mcp-init                          # config/, mcp_apps/, personas/, skills/
```

`willow-mcp-init` already lays down the `WILLOW_HOME` structure (config, ACL
manifests, personas, skills, seeds, gate ledger dirs); this blueprint adds the
data schemas and the key underneath it. Together they stand up a complete,
empty, sovereign box.

## The box layout (never in git)

```
<box>/                       # 0700
  vault.db   vault.key       # secrets + Fernet key (0600)
  db/
    soil.db  receipts.db  kart.db
  config/                    # settings.global.json (consent), roster, specialists
  mcp_apps/<app_id>/         # per-app ACL manifests
  ledgers/                   # willow-gate PGP check-in ledger
  # Postgres KB: external, adaptive
```

Design rationale and the full decision log (D1–D7) live in
`safe-app-store/docs/design/safe-app-installer.md`.
