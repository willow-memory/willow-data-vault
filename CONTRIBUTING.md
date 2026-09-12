# Contributing

This repo is a blueprint: schemas and two bootstrap scripts, never data. CI
runs what already exists here and nothing more (fleet plan decision 10). Every
command below is the exact one `.github/workflows/tests.yml` runs, so a green
local run is the same evidence CI produces. Linux only — there is no package to
build, and the box only ever runs on Linux.

## Run what CI runs

Provision an empty box and walk the receipts chain (job `provision`):

    bootstrap/provision.sh /tmp/box
    python3 bootstrap/verify_receipts.py /tmp/box/mcp_receipt.db
    python3 bootstrap/verify_receipts.py --self-test
    python3 bootstrap/vault_intake.py --self-test
    sqlite3 /tmp/scratch-vault.db < schema/01_secrets.sql
    sqlite3 /tmp/scratch-store.db < schema/02_soil_records.sql
    git status --porcelain            # must print nothing: provisioning never touches the repo

`provision.sh` applies `03_receipts.sql` then `04_tasks.sqlite.sql` (that order
is the script's own) and runs the verifier itself; the two explicit
`verify_receipts.py` lines repeat that on the fresh db and prove the guard
refuses a tampered row. `vault_intake.py` applies `06_intake.sql` on its own.
`01_secrets.sql` and `02_soil_records.sql` are applied to throwaway databases
only to prove the DDL executes — willow-mcp owns their creation in a real box.

Lint every schema (job `sql-lint`; pinned version, rule exclusions and their
reasons in `.sqlfluff`):

    pip install "sqlfluff==4.3.0"
    sqlfluff lint --dialect sqlite   schema/01_secrets.sql schema/02_soil_records.sql schema/03_receipts.sql schema/04_tasks.sqlite.sql schema/06_intake.sql
    sqlfluff lint --dialect postgres schema/04_tasks.postgres.sql schema/05_knowledge.reference.sql

Check the workflow's schema list against the files on disk (job `wiring`):

    python3 -m unittest discover -s tests -v

The aggregate job `test` needs every leg and fails on any result other than
`success`; it is the one check to require on `main`. `codeql.yml` analyzes the
`actions` language only — there is no Python package here for CodeQL to
analyze.

## What CI will not do

It will not write to a schema. If `verify_receipts.py` or the lint fails
against a fresh provision, that is a finding to report on the PR, not a
reason to edit `schema/` to fit the check. The schemas marked verbatim in the
README are owned upstream (willow-mcp, kartikeya) and change there first.

## The Idea-Id commit-trailer convention

A commit that lands an idea recorded in docs/ideas.md carries an
`Idea-Id: <corpus>-ideas-<num>` git trailer (add `Idea-Status: partial` when a
commit only partly lands it). It is the durable join key willow-reconciler
reads; a wrong id is worse than no id, so never type one by hand:

    reconciler id --repo ./ --doc docs/ideas.md --grep "words from the item"
    reconciler install-hook --repo ./       # derives it from a branch named idea-NN

`.github/workflows/trailers.yml` runs `reconciler verify` on every PR and fails
on a trailer that names an item the doc does not contain.

Pass the repo as `./` (or an absolute path), not a bare `.`: willow-reconciler
0.6.0 reads a bare `.` as a repo name to look up beside the checkout and exits 2.
