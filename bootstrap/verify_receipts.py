#!/usr/bin/env python3
"""verify_receipts.py — walk the receipts hash chain and refuse on a broken link.

Companion to schema/03_receipts.sql's prev_hash/hash columns: a tamper-evidence
layer pattern-ported from Nestor's hash-chained ledger (nestor/ledger.py,
Apache-2.0, github.com/rudi193-cmd/Nestor, pinned v0.2.0). No Nestor code is
copied verbatim — this is the same prev-is-a-hash-of-the-previous-entry chain,
reimplemented against a SQL table instead of a JSONL file, in this repo's own
idiom (a single stdlib-only script, the same "shell out to python3" shape
provision.sh already uses for the parts sqlite3-the-CLI cannot do). No new
runtime is introduced: python3 was already an accepted fallback dependency here
(see provision.sh's schema-apply and vault.key steps), and this uses nothing
outside the standard library.

A broken chain is a REFUSAL — nonzero exit, no partial credit — matching
nestor.ledger.verify's contract, not a lint that prints and continues.

Usage:
    verify_receipts.py /path/to/box/mcp_receipt.db
    verify_receipts.py --self-test        # prove a tampered row IS refused

Exit codes:
    0   chain intact (or no receipts db yet — nothing to verify)
    1   chain broken — a row's hash does not match its stored value, or a
        prev_hash does not match the previous row's hash (tamper, or a
        row/rows removed or reordered)
    2   the receipts table exists but predates prev_hash/hash (an
        unmigrated box) — NOT a tamper finding, but still a refusal: this
        script cannot vouch for a chain that was never started
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile

GENESIS = "genesis"


def canonical_row(id_, ts, app_id, tool, outcome, detail, prev_hash) -> str:
    """The exact JSON form each row's `hash` is computed over.

    Key order and separators matter — this must serialize identically every
    time the same values are hashed, on whichever side (writer or verifier)
    computes it. Mirrors nestor.ledger's convention: json.dumps with the
    default (", ", ": ") separators and ensure_ascii=False.
    """
    obj = {
        "id": id_,
        "ts": ts,
        "app_id": app_id,
        "tool": tool,
        "outcome": outcome,
        "detail": detail,
        "prev_hash": prev_hash,
    }
    return json.dumps(obj, ensure_ascii=False)


def row_hash(id_, ts, app_id, tool, outcome, detail, prev_hash) -> str:
    line = canonical_row(id_, ts, app_id, tool, outcome, detail, prev_hash)
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def verify_chain(db_path: str) -> tuple[int, str]:
    """Walk the receipts table in id order. Returns (exit_code, detail).

    0 = intact, 1 = broken chain (tamper/reorder/deletion), 2 = unmigrated
    table (no prev_hash/hash columns — never chained, not tampered).
    """
    con = sqlite3.connect(db_path)
    try:
        try:
            rows = con.execute(
                "SELECT id, ts, app_id, tool, outcome, detail, prev_hash, hash "
                "FROM receipts ORDER BY id ASC"
            ).fetchall()
        except sqlite3.OperationalError as e:
            return 2, (
                f"cannot verify: {e} — this receipts.db predates the "
                f"prev_hash/hash columns in schema/03_receipts.sql. Not a "
                f"tamper finding: the chain was never started here. An "
                f"in-place migration (ALTER TABLE ADD COLUMN) is required "
                f"before this box can be verified; out of scope for this "
                f"schema-and-bootstrap-only change."
            )
    finally:
        con.close()

    prev = GENESIS
    for (id_, ts, app_id, tool, outcome, detail, prev_hash, stored_hash) in rows:
        if prev_hash != prev:
            return 1, (
                f"broken chain at receipts.id={id_}: prev_hash={prev_hash!r}, "
                f"expected {prev!r} (the hash of the previous row) — a row was "
                f"edited, inserted out of order, or removed"
            )
        expected = row_hash(id_, ts, app_id, tool, outcome, detail, prev_hash)
        if stored_hash != expected:
            return 1, (
                f"broken chain at receipts.id={id_}: stored hash {stored_hash!r} "
                f"does not match its own canonical form (recomputed "
                f"{expected!r}) — this row's columns were changed after it was "
                f"hashed"
            )
        prev = stored_hash

    return 0, f"intact — {len(rows)} row(s)"


def _build_test_db(db_path: str, schema_path: str) -> None:
    con = sqlite3.connect(db_path)
    try:
        con.executescript(open(schema_path, encoding="utf-8").read())
        rows = [
            ("2026-01-01T00:00:00+00:00", "quick-stupids", "task_submit", "ok", "seeded"),
            ("2026-01-01T00:00:05+00:00", "quick-stupids", "knowledge_search", "ok", None),
            ("2026-01-01T00:00:09+00:00", "willow-mcp", "task_submit", "denied", "store_scope"),
        ]
        prev = GENESIS
        for i, (ts, app_id, tool, outcome, detail) in enumerate(rows, start=1):
            h = row_hash(i, ts, app_id, tool, outcome, detail, prev)
            con.execute(
                "INSERT INTO receipts (id, ts, app_id, tool, outcome, detail, "
                "prev_hash, hash) VALUES (?,?,?,?,?,?,?,?)",
                (i, ts, app_id, tool, outcome, detail, prev, h),
            )
            prev = h
        con.commit()
    finally:
        con.close()


def self_test() -> int:
    """Build a correctly-chained receipts db, confirm it verifies OK, then
    commit the forbidden act — edit a past row in place — and confirm THAT
    is refused. Exits 0 only if both halves behaved as required; a self-test
    that fails to detect tampering is itself a critical failure of this
    guard, not a pass.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(here, "..", "schema", "03_receipts.sql")

    fd, db_path = tempfile.mkstemp(prefix="verify_receipts_selftest_", suffix=".db")
    os.close(fd)
    try:
        _build_test_db(db_path, schema_path)

        print("-- self-test: freshly-written, untampered chain --")
        code, detail = verify_chain(db_path)
        print(f"   {detail}")
        if code != 0:
            print(
                f"SELF-TEST FAILED: a clean chain did not verify (exit {code}). "
                f"The verifier itself is broken.",
                file=sys.stderr,
            )
            return 1

        print("-- self-test: tampering row id=2 (detail) — the forbidden act --")
        con = sqlite3.connect(db_path)
        try:
            con.execute("UPDATE receipts SET detail = 'TAMPERED' WHERE id = 2;")
            con.commit()
        finally:
            con.close()

        code, detail = verify_chain(db_path)
        print(f"   {detail}")
        if code == 0:
            print(
                "SELF-TEST FAILED: a tampered row verified as OK — the chain "
                "does not detect tampering.",
                file=sys.stderr,
            )
            return 1
        if code != 1:
            print(
                f"SELF-TEST FAILED: tampering produced exit {code}, expected 1 "
                f"(broken chain), got a different refusal reason instead.",
                file=sys.stderr,
            )
            return 1

        print("-- self-test PASSED: clean chain verified, tamper was refused --")
        return 0
    finally:
        try:
            os.remove(db_path)
        except OSError:
            pass


def main(argv: list[str]) -> int:
    if argv[:1] == ["--self-test"]:
        return self_test()

    if len(argv) != 1:
        print(
            "usage: verify_receipts.py /path/to/box/mcp_receipt.db\n"
            "       verify_receipts.py --self-test",
            file=sys.stderr,
        )
        return 2

    db_path = argv[0]
    if not os.path.exists(db_path):
        print(f"no receipts db at {db_path} — nothing to verify (a fresh box has none yet)")
        return 0

    code, detail = verify_chain(db_path)
    if code == 0:
        print(f"receipts chain OK: {detail}")
    else:
        print(f"receipts chain REFUSED: {detail}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
