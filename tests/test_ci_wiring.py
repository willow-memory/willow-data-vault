"""CI wiring: the schema lists in .github/workflows/tests.yml equal the files
on disk. Stdlib unittest only — this repo installs no test runner.

The workflow keeps two space-separated lists (SQLITE_SCHEMAS, POSTGRES_SCHEMAS)
as single env lines. A schema added to schema/ without an entry in one of the
two lists, or listed in both, or listed but missing, fails here — so the lint
leg can never silently skip a file. No YAML parser is used on purpose: the
stdlib has none, and the two lines are the only thing this test needs.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
SCHEMA_DIR = ROOT / "schema"


def _env_list(text: str, key: str) -> list[str]:
    m = re.search(rf"^\s*{re.escape(key)}:\s*(.+?)\s*$", text, re.MULTILINE)
    if m is None:
        raise AssertionError(f"{WORKFLOW.name} has no `{key}:` line")
    return m.group(1).split()


class WorkflowSchemaList(unittest.TestCase):
    def setUp(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.sqlite = _env_list(text, "SQLITE_SCHEMAS")
        self.postgres = _env_list(text, "POSTGRES_SCHEMAS")
        self.on_disk = sorted(
            p.relative_to(ROOT).as_posix() for p in SCHEMA_DIR.glob("*.sql")
        )

    def test_workflow_lists_exactly_the_schemas_on_disk(self) -> None:
        listed = sorted(self.sqlite + self.postgres)
        self.assertEqual(listed, self.on_disk)

    def test_no_schema_is_listed_under_both_dialects(self) -> None:
        self.assertEqual(set(self.sqlite) & set(self.postgres), set())

    def test_dialect_partition_matches_filenames(self) -> None:
        # The Postgres files say so in their name or their header; everything
        # else is SQLite. Keeps a future schema from landing in the wrong lint.
        for path in self.postgres:
            head = (ROOT / path).read_text(encoding="utf-8")[:600]
            self.assertTrue(
                "postgres" in path or "Postgres" in head,
                f"{path} is linted as Postgres but does not say it is",
            )
        for path in self.sqlite:
            self.assertNotIn("postgres", path)


class WorkflowRunsWhatExists(unittest.TestCase):
    def test_receipts_verifier_and_provision_are_wired(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("bootstrap/provision.sh", text)
        self.assertIn("bootstrap/verify_receipts.py", text)


if __name__ == "__main__":
    unittest.main()
