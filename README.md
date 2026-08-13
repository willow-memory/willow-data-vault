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
  02_soil_records.sql        # SOIL store (SQLite) — owned; per-collection, applied lazily
  03_receipts.sql            # tool-call ledger (SQLite)      — owned + tamper-evidence
  04_tasks.sqlite.sql        # Kart task queue (SQLite)       — owned, verbatim
  04_tasks.postgres.sql      # Kart task queue (Postgres)     — owned, verbatim
  05_knowledge.reference.sql # KB (Postgres) — REFERENCE ONLY, willow ADAPTS
bootstrap/
  provision.sh               # stand up an empty box from the schemas
  verify_receipts.py         # walk the receipts hash chain; a broken chain refuses
```

### Receipts hash chain (tamper-evidence)

`03_receipts.sql`'s base five columns (`id, ts, app_id, tool, outcome, detail`)
are owned, verbatim, from willow-mcp `receipts.py`. Two more —
`prev_hash, hash` — are this repo's give-back: a hash chain over the row
stream, pattern-ported from Nestor's hash-chained ledger
(`nestor/ledger.py`, Apache-2.0, `github.com/rudi193-cmd/Nestor`, pinned
`v0.2.0`). Editing a past row breaks the next row's `prev_hash` on re-hash —
`bootstrap/verify_receipts.py` is the verifier, and `provision.sh` runs it
after applying the receipts schema, so a broken chain **refuses to
provision** (nonzero exit) instead of silently continuing. Run
`bootstrap/verify_receipts.py --self-test` to see the guard build a clean
chain, verify it, tamper a row, and confirm that IS refused.

This is schema-only: the columns are `NOT NULL`, so willow-mcp's
`receipts.py` insert path has to compute and supply them for every new row —
that writer-side patch lives in willow-mcp, out of scope here. A box
provisioned before this change has a receipts table without these columns;
`verify_receipts.py` reports that state explicitly (exit 2) rather than
mistaking "never chained" for "tampered" (exit 1). See `03_receipts.sql`'s
header for the exact canonical row form the hash is computed over.

Covenant: this chain adds tamper-*evidence* to the receipts trail. It seals
nothing and grants no authority — a clean chain says the rows were not
altered after being written, not that anything in them was approved.

The SQLite/Postgres store schemas are **owned** by willow/Kart and copied
verbatim from `willow-mcp` and `kartikeya`. `provision.sh` materializes the two
that are safe to pre-create (receipts, Kart-SQLite) at the box root. The other
two are created by willow-mcp itself, to preserve an invariant the code owns:
`01_secrets.sql` (vault.db) is only ever written **alongside** `vault.key` as an
atomic pair — willow-mcp fails closed on a keyless vault — and
`02_soil_records.sql` is the per-collection SOIL shape, applied the first time a
collection is written. The knowledge base is **not owned**:
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
  mcp_receipt.db             # tool-call receipts — the audit trail, stays in the box
  kart.db                    # Kart task queue (SQLite fallback; Postgres used if present)
  <collection>/store.db      # SOIL store — one dir per collection, created lazily on first write
  config/                    # settings.global.json (consent), roster, specialists
  mcp_apps/<app_id>/         # per-app ACL manifests
  ledgers/                   # willow-gate PGP check-in ledger
  # Postgres KB + tasks: external, adaptive
```

These filenames and locations are exactly where willow-mcp resolves each store
at runtime (`vault.py`, `receipts.py`, `db.py`, `task_queue.py`) with
`WILLOW_HOME == WILLOW_STORE_ROOT == <box>`. There is no `db/` subdirectory: the
stores live at the box root, and SOIL is per-collection, not a single file.

Design rationale and the full decision log (D1–D7) live in
`safe-app-store/docs/design/safe-app-installer.md`.
