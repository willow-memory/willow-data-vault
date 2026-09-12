# willow-data-vault — the idea pile

This file is read by `reconciler run --repo ./ --doc docs/ideas.md --validate`
(willow-reconciler). It is the repo's own record of what has been proposed and
what has landed; the reconciler reads it back against git history and reports
the gap. Keep it short and keep it true — an item goes here only when the repo's
own text already names it as open.

Legend: ✅ shipped · 🟡 partial · (untagged) proposed

**Numbers are permanent join keys.** `reconciler/ids.py` derives
`<corpus>-ideas-<num>` from the number written on the line, so a number is an
identity, not an ordinal. Never renumber; never write a markdown-auto-numbered
list — retire a number instead and leave the gap.

A legend tag counts only when it LEADS the item text. Tag ✅/🟡 only where git
history shows it; a commit that lands an item carries its `Idea-Id` trailer
(see CONTRIBUTING.md), which is the evidence the reconciler ranks highest.

## A. CI floor — run what exists (fleet plan decision 10)

1. CI that runs `bootstrap/verify_receipts.py` and a SQL lint over the seven schemas (fleet plan Wave 4, C4-vault-ci). Provision an empty box the way `bootstrap/provision.sh` already does, walk the receipts chain, lint every `schema/*.sql`; nothing new is written to the schemas.

2. adopt `Idea-Id` commit trailers (fleet CONVENTION, decision-2026-09-11). `.github/workflows/trailers.yml` runs `reconciler verify` on every PR so a trailer that names an item this doc does not contain fails the build.

## B. Receipts chain — gaps the schema names itself

3. An in-place `ALTER TABLE ADD COLUMN` migration for a receipts table provisioned before `prev_hash`/`hash` existed. `schema/03_receipts.sql`'s header says `provision.sh` does not attempt it, and `bootstrap/verify_receipts.py` reports that box as exit 2 ("unmigrated, not tampered") rather than verifying it.

4. A separately-recorded expected chain head kept outside the box, so the walk vouches for the last row too. `schema/03_receipts.sql` states the limit up front: the chain vouches for every row except the last, and "this schema does not do that on its own".
