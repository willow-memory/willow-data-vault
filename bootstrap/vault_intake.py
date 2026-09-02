#!/usr/bin/env python3
"""vault_intake.py — answer "do I already hold this?" by bytes, then file what's new.

Companion to schema/06_intake.sql. Two subcommands:

    index   walk the box, SHA-256 every file AND every archive member, write
            the content index.
    scan    reconcile a source folder against that index: report what the box
            already holds, what is genuinely new, and what collides. Moves
            nothing unless --apply is given.

WHY BY BYTES. Asking by filename gets the answer wrong in both directions. It
re-files things the box already has under another name, and it cannot see into
an archive at all. Measured on a real box, 2026-09-01: a name-based `find`
reported conversations.json, memories.json and users.json as absent; all three
were inside knowledge-extractions.tar.gz under personal/knowledge/claude-ai-
exports/. The box had held them for months. So identity here is the digest, and
archive members are indexed as first-class rows.

DRY RUN IS THE DEFAULT, and --apply is the only thing that moves a byte. A
source file that is already in the box is never deleted by this script: knowing
you have a second copy and deciding to destroy one are different acts, and only
the second needs a human. `scan --apply` files NEW items and leaves duplicates
exactly where they are, naming where the box already holds them.

Covenant: this builds a finding aid. It seals nothing, verifies nothing, and
grants nothing. A digest in the index says these bytes are in the box — not
that they are correct, current, or approved. Same posture as the receipts
chain: evidence, never authority.

Stdlib only, like the rest of bootstrap/. No new runtime.

Usage:
    vault_intake.py index --vault ~/sean-data-vault
    vault_intake.py scan  --vault ~/sean-data-vault --source ~/inbox
    vault_intake.py scan  --vault ~/sean-data-vault --source ~/inbox --apply
    vault_intake.py --self-test

Exit codes:
    0   clean — nothing new, or --apply filed everything it proposed
    1   a human is needed — new items with no confident destination, or a name
        collision where the bytes differ. Reported, never guessed at.
    2   refusal — the vault path is missing or is not a directory
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / "schema" / "06_intake.sql"
DEFAULT_DB = ".vault-index.db"
ARCHIVE_CAP = 256 * 1024 * 1024      # don't stream-hash archives bigger than this
CHUNK = 1024 * 1024

# ── the routing table ───────────────────────────────────────────────────────
# Deliberately a flat, readable table rather than a classifier. Somebody should
# be able to read this and argue with it. An extension that is not listed gets
# no destination, which is a REFUSAL to guess, not a failure — those land in
# the report for a human. Order matters: first match wins.
ROUTES: list[tuple[str, str, tuple[str, ...]]] = [
    # (suffix or glob-ish token,      destination dir,     derived tags)
    (".sql.gz",                       "postgres",          ("dump", "postgres")),
    (".dump",                         "postgres",          ("dump", "postgres")),
    (".sql",                          "postgres",          ("dump", "postgres")),
    (".ledger.jsonl",                 "mcp",               ("ledger", "append-only")),
    (".db",                           "mcp",               ("sqlite",)),
    (".sqlite",                       "mcp",               ("sqlite",)),
    (".sqlite3",                      "mcp",               ("sqlite",)),
    (".jpg",                          "personal",          ("image", "photo")),
    (".jpeg",                         "personal",          ("image", "photo")),
    (".png",                          "personal",          ("image",)),
    (".heic",                         "personal",          ("image", "photo")),
    (".mp4",                          "personal",          ("video",)),
    (".m4a",                          "personal",          ("audio",)),
    (".pdf",                          "docs",              ("document",)),
    (".docx",                         "docs",              ("document",)),
    (".xlsx",                         "docs",              ("spreadsheet",)),
    (".csv",                          "docs",              ("tabular",)),
    (".md",                           "docs",              ("text",)),
    (".txt",                          "docs",              ("text",)),
    (".html",                         "docs",              ("text", "html")),
    (".json",                         "knowledge-json",    ("structured",)),
    (".tar.gz",                       "downloads-misc",    ("archive",)),
    (".tgz",                          "downloads-misc",    ("archive",)),
    (".zip",                          "downloads-misc",    ("archive",)),
]

# Never routed automatically, whatever the extension says. Each is here for a
# stated reason, not a hunch.
REFUSE: dict[str, str] = {
    ".part":       "an incomplete download — not content yet",
    ".crdownload": "an incomplete download — not content yet",
    ".appimage":   "an application binary; the vault holds data, not tooling",
    ".key":        "key material never enters an indexed store; see the vault.key covenant",
    ".pem":        "key material never enters an indexed store; see the vault.key covenant",
}

ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar", ".zip")

# ── set rules ───────────────────────────────────────────────────────────────
# Some things are only legible together. A Claude data export is ~30 UUID-named
# .json files beside conversations.json / memories.json / users.json; filed one
# by one they become thirty anonymous blobs and the export stops being an
# export. The routing table above is per-file and cannot express that.
#
# A set rule fires only when its MARKERS are all present in the same scan —
# that is the evidence the loose files belong to one thing rather than merely
# sharing a suffix. Members then go to one dated directory together, matching
# the convention the box already uses
# (personal/knowledge/claude-ai-exports/data-<date>-batch-0000/).
SETS: list[dict] = [
    {
        "name": "claude-export",
        "markers": {"conversations.json", "memories.json", "users.json"},
        # Membership is a NAME SHAPE, not merely the suffix. Matching every
        # .json in the scan over-captured on the first real run: two
        # sean_session_db.json files — unrelated session dumps that happened to
        # share the folder — were swept into the export. A set rule that fires
        # on "same extension, same folder" is a folder rule wearing a costume.
        "member_re": re.compile(
            r"^(conversations|memories|users)\.json$"
            r"|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$",
            re.I),
        "dest": "personal/knowledge/claude-ai-exports/intake-{date}",
        "tags": ("claude-export", "structured", "set"),
    },
]

# The empty digest. Every zero-length file has it, so "the box already holds
# this" is TRUE and USELESS for them — an empty .jpg would match an empty .md
# and the tool would report a photo as already filed. Found the hard way on a
# real box, 2026-09-01: a 0-byte 20260517_221317.jpg and a 0-byte
# Cursor.AppImage (two failed downloads) both "matched" a LOOKATME.md inside a
# tarball, because the vault held 20 zero-byte objects of its own.
#
# So zero-length files are not content: they are never indexed as objects and
# never counted as duplicates. A 0-byte file in a source folder is a failed
# download, and it goes to the human pile with .part and friends.
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def sha_stream(fh) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    for block in iter(lambda: fh.read(CHUNK), b""):
        h.update(block)
        n += len(block)
    return h.hexdigest(), n


def suffix_of(name: str) -> str:
    low = name.lower()
    for compound in (".tar.gz", ".sql.gz", ".ledger.jsonl"):
        if low.endswith(compound):
            return compound
    return os.path.splitext(low)[1]


def connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)

    # Migrate BEFORE applying the schema, not after. CREATE TABLE IF NOT EXISTS
    # will not add a column to a table that already exists, and the schema now
    # also declares an index ON vault_intake_log (run_id) — so on a database
    # built before run_id existed, executescript() dies on the CREATE INDEX
    # before any later migration could run. Fresh databases hid this
    # completely; it only appears on an upgrade, which is the case that
    # matters. Additive and idempotent; old rows keep run_id NULL, which reads
    # correctly as "written before runs were tracked".
    have_log = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vault_intake_log'"
    ).fetchone()
    if have_log:
        cols = {r[1] for r in con.execute("PRAGMA table_info(vault_intake_log)")}
        if "run_id" not in cols:
            con.execute("ALTER TABLE vault_intake_log ADD COLUMN run_id INTEGER")
            con.commit()

    con.executescript(SCHEMA.read_text())
    return con


# ── index ───────────────────────────────────────────────────────────────────

def do_index(vault: Path, db_path: Path, cap: int) -> int:
    con = connect(db_path)
    run = con.execute(
        "INSERT INTO vault_intake_runs (started_at, vault_root, applied) VALUES (?,?,0)",
        (now(), str(vault)),
    ).lastrowid

    seen = read = skipped = 0
    con.execute("DELETE FROM vault_objects")     # a full re-index, not a merge

    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            p = Path(root) / name
            if p.is_symlink() or not p.is_file():
                continue
            rel = str(p.relative_to(vault))
            if rel == db_path.name:
                continue
            try:
                st = p.stat()
                if st.st_size == 0:
                    continue            # not content — see EMPTY_SHA
                digest = sha_file(p)
            except OSError:
                continue
            con.execute(
                "INSERT OR REPLACE INTO vault_objects "
                "(sha256,size,rel_path,container,member_path,mtime,indexed_at) "
                "VALUES (?,?,?,NULL,NULL,?,?)",
                (digest, st.st_size, rel, st.st_mtime, now()),
            )
            seen += 1
            for tag in derive_tags(name, rel):
                con.execute("INSERT OR IGNORE INTO vault_tags (sha256,tag) VALUES (?,?)",
                            (digest, tag))

            low = name.lower()
            if low.endswith(ARCHIVE_SUFFIXES):
                if st.st_size > cap:
                    skipped += 1
                    continue
                try:
                    n = index_archive(con, p, rel)
                    read += 1
                    seen += n
                except Exception:
                    skipped += 1

    con.execute(
        "UPDATE vault_intake_runs SET finished_at=?, objects_seen=?, archives_read=?, "
        "archives_skipped=? WHERE id=?",
        (now(), seen, read, skipped, run),
    )
    con.commit()
    print(f"indexed {seen} objects · {read} archives read · {skipped} archives skipped "
          f"(> {cap // (1024*1024)} MB or unreadable)")
    print(f"index: {db_path}")
    return 0


def index_archive(con: sqlite3.Connection, path: Path, rel: str) -> int:
    n = 0
    low = path.name.lower()
    if low.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                with zf.open(info) as fh:
                    digest, size = sha_stream(fh)
                if size == 0:
                    continue            # not content — see EMPTY_SHA
                con.execute(
                    "INSERT OR REPLACE INTO vault_objects "
                    "(sha256,size,rel_path,container,member_path,mtime,indexed_at) "
                    "VALUES (?,?,?,?,?,NULL,?)",
                    (digest, size, rel, rel, info.filename, now()),
                )
                n += 1
    else:
        with tarfile.open(path, "r:*") as tf:
            for member in tf:
                if not member.isfile():
                    continue
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                digest, size = sha_stream(fh)
                if size == 0:
                    continue            # not content — see EMPTY_SHA
                con.execute(
                    "INSERT OR REPLACE INTO vault_objects "
                    "(sha256,size,rel_path,container,member_path,mtime,indexed_at) "
                    "VALUES (?,?,?,?,?,NULL,?)",
                    (digest, size, rel, rel, member.name, now()),
                )
                n += 1
    return n


def derive_tags(name: str, rel: str) -> set[str]:
    tags: set[str] = set()
    suf = suffix_of(name)
    for token, _dest, tt in ROUTES:
        if suf == token:
            tags.update(tt)
            break
    top = rel.split(os.sep, 1)[0]
    if top and top != name:
        tags.add(f"area:{top}")
    return tags


# ── scan ────────────────────────────────────────────────────────────────────

def route(name: str) -> tuple[str | None, tuple[str, ...], str | None]:
    suf = suffix_of(name)
    if suf in REFUSE:
        return None, (), REFUSE[suf]
    for token, dest, tags in ROUTES:
        if suf == token:
            return dest, tags, None
    return None, (), f"no route for '{suf or name}'"


def do_scan(vault: Path, source: Path, db_path: Path, apply: bool) -> int:
    con = connect(db_path)
    have = {r[0] for r in con.execute("SELECT sha256 FROM vault_objects")}
    if not have:
        print("index is empty — run `index` first", file=sys.stderr)
        return 2

    run = con.execute(
        "INSERT INTO vault_intake_runs (started_at, vault_root, source_root, applied) "
        "VALUES (?,?,?,?)",
        (now(), str(vault), str(source), 1 if apply else 0),
    ).lastrowid

    # Which set rules fire for this source? Markers must all be present.
    present = {p.name for p in source.rglob("*") if p.is_file()}
    active_sets = []
    for rule in SETS:
        if rule["markers"] <= present:
            dest = rule["dest"].format(date=datetime.now(timezone.utc).date().isoformat())
            active_sets.append((rule, dest))
            print(f"set rule '{rule['name']}' fired — markers all present; "
                  f"members group into {dest}/")

    dup: list[tuple[str, str]] = []
    new: list[tuple[Path, str, str, tuple[str, ...]]] = []
    held: list[tuple[str, str]] = []
    for p in sorted(source.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        try:
            digest = sha_file(p)
            size = p.stat().st_size
        except OSError:
            con.execute("INSERT INTO vault_intake_log "
                        "(run_id,ts,src_path,verdict,action,note) "
                        "VALUES (?,?,?,'unreadable','refused','could not read')",
                        (run, now(), str(p)))
            continue

        if size == 0:
            held.append((p.name, "zero bytes — a failed download, not content"))
            con.execute(
                "INSERT INTO vault_intake_log "
                "(run_id,ts,src_path,sha256,size,verdict,action,note) "
                "VALUES (?,?,?,?,0,'new','skipped','zero bytes — not content')",
                (run, now(), str(p), digest))
            continue

        if digest in have:
            where = con.execute(
                "SELECT rel_path, member_path FROM vault_objects WHERE sha256=? LIMIT 1",
                (digest,)).fetchone()
            loc = where[0] + (f" :: {where[1]}" if where[1] else "")
            dup.append((p.name, loc))
            con.execute(
                "INSERT INTO vault_intake_log "
                "(run_id,ts,src_path,sha256,size,verdict,action,held_at) "
                "VALUES (?,?,?,?,?,'duplicate','reported',?)",
                (run, now(), str(p), digest, size, loc))
            continue

        dest = tags = why = None
        for rule, set_dest in active_sets:
            if rule["member_re"].match(p.name):
                # Keep the source's own shape inside the set. The first real run
                # flattened 25 files from projects/ and 3 from design_chats/
                # into one directory, which preserved set MEMBERSHIP and threw
                # away set STRUCTURE — the same mistake one level up.
                sub = p.parent.relative_to(source)
                dest = set_dest if str(sub) == "." else f"{set_dest}/{sub}"
                tags = rule["tags"] + (f"set:{rule['name']}",)
                break
        if dest is None:
            dest, tags, why = route(p.name)
        if dest is None:
            held.append((p.name, why or "unrouted"))
            con.execute(
                "INSERT INTO vault_intake_log "
                "(run_id,ts,src_path,sha256,size,verdict,action,note) "
                "VALUES (?,?,?,?,?,'new','skipped',?)",
                (run, now(), str(p), digest, size, why))
            continue
        new.append((p, digest, dest, tags))

    filed = 0
    for p, digest, dest, tags in new:
        target_dir = vault / dest
        target = target_dir / p.name
        if target.exists() and sha_file(target) != digest:
            held.append((p.name, f"name collision in {dest}/ with different bytes"))
            con.execute(
                "INSERT INTO vault_intake_log "
                "(run_id,ts,src_path,sha256,verdict,action,note) "
                "VALUES (?,?,?,?,'name_conflict','refused',?)",
                (run, now(), str(p), digest,
                 f"{dest}/{p.name} exists with different bytes"))
            continue
        if apply:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(target))
            st = target.stat()
            con.execute(
                "INSERT OR REPLACE INTO vault_objects "
                "(sha256,size,rel_path,container,member_path,mtime,indexed_at) "
                "VALUES (?,?,?,NULL,NULL,?,?)",
                (digest, st.st_size, f"{dest}/{p.name}", st.st_mtime, now()))
            for tag in set(tags) | {f"area:{dest}", "via:intake"}:
                con.execute("INSERT OR IGNORE INTO vault_tags (sha256,tag) VALUES (?,?)",
                            (digest, tag))
            filed += 1
        con.execute(
            "INSERT INTO vault_intake_log "
            "(run_id,ts,src_path,sha256,verdict,action,dest,note) "
            "VALUES (?,?,?,?,'new',?,?,?)",
            (run, now(), str(p), digest, "filed" if apply else "reported",
             f"{dest}/{p.name}", ",".join(sorted(tags))))

    con.execute("UPDATE vault_intake_runs SET finished_at=? WHERE id=?", (now(), run))
    con.commit()

    print(f"\n  already in the box   {len(dup)}")
    for name, loc in dup[:40]:
        print(f"      {name}  ->  {loc}")
    if len(dup) > 40:
        print(f"      ... and {len(dup) - 40} more")

    routed = [n for n in new if n[0].name not in {h[0] for h in held}]
    print(f"\n  new, routed          {len(routed)}"
          f"{'  (filed)' if apply else '  (dry run — nothing moved)'}")
    for p, _d, dest, tags in routed[:40]:
        print(f"      {p.name}  ->  {dest}/   [{','.join(sorted(tags))}]")
    if len(routed) > 40:
        print(f"      ... and {len(routed) - 40} more")

    print(f"\n  needs a human        {len(held)}")
    for name, why in held[:40]:
        print(f"      {name}  —  {why}")
    if len(held) > 40:
        print(f"      ... and {len(held) - 40} more")

    if apply:
        print(f"\nfiled {filed}. duplicates left where they are — deleting a second "
              f"copy is a separate decision.")
    return 1 if held else 0


# ── self test ───────────────────────────────────────────────────────────────

def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        vault, src = tmp / "vault", tmp / "src"
        (vault / "docs").mkdir(parents=True)
        src.mkdir()

        (vault / "docs" / "already.md").write_text("held bytes\n")
        inner = tmp / "inner.txt"
        inner.write_text("archived bytes\n")
        with tarfile.open(vault / "bundle.tar.gz", "w:gz") as tf:
            tf.add(inner, arcname="deep/inner.txt")

        (src / "already-renamed.md").write_text("held bytes\n")      # dup by bytes
        (src / "inner-copy.txt").write_text("archived bytes\n")      # dup inside archive
        (src / "brand-new.md").write_text("fresh\n")                 # new
        (src / "half.part").write_text("nope\n")                     # refused
        (vault / "docs" / "stub.md").write_text("")                  # box holds an empty file
        (src / "failed-download.jpg").write_text("")                 # 0 bytes — must NOT match it

        # a set: markers at the root, a member in a subdirectory, and an
        # unrelated .json that must NOT be swept in
        for m in ("conversations.json", "memories.json", "users.json"):
            (src / m).write_text(f"{m} body\n")
        (src / "projects").mkdir()
        (src / "projects" / "019a6a72-ae02-7363-85ff-45dc01c86299.json").write_text("member\n")
        (src / "sean_session_db.json").write_text("unrelated\n")

        db = tmp / "idx.db"
        assert do_index(vault, db, ARCHIVE_CAP) == 0
        con = sqlite3.connect(db)
        n = con.execute("SELECT count(*) FROM vault_objects WHERE container IS NOT NULL").fetchone()[0]
        assert n == 1, f"archive member not indexed (got {n})"
        con.close()

        print("\n-- dry run --")
        rc = do_scan(vault, src, db, apply=False)
        assert (src / "brand-new.md").exists(), "dry run moved a file"
        assert rc == 1, "refused .part should require a human"

        print("\n-- apply --")
        do_scan(vault, src, db, apply=True)
        assert (vault / "docs" / "brand-new.md").exists(), "new file was not filed"
        assert (src / "already-renamed.md").exists(), "duplicate was deleted — it must not be"
        assert (src / "inner-copy.txt").exists(), "archive-member duplicate was deleted"
        assert (src / "failed-download.jpg").exists(), \
            "a 0-byte file was filed or matched — empty must never count as held"
        con = sqlite3.connect(db)
        empties = con.execute("SELECT count(*) FROM vault_objects WHERE size=0").fetchone()[0]
        runs = con.execute("SELECT count(DISTINCT run_id) FROM vault_intake_log").fetchone()[0]
        con.close()
        assert empties == 0, f"zero-byte objects entered the index ({empties})"
        assert runs >= 2, f"log rows are not separated by run (got {runs} distinct run_ids)"

        exp = vault / "personal/knowledge/claude-ai-exports"
        day = sorted(exp.iterdir())[0]
        assert (day / "conversations.json").exists(), "set marker not filed into the set"
        assert (day / "projects" / "019a6a72-ae02-7363-85ff-45dc01c86299.json").exists(), \
            "set member lost its source subdirectory — structure was flattened"
        assert (vault / "knowledge-json" / "sean_session_db.json").exists(), \
            "an unrelated .json was swept into the set by extension alone"

        # Upgrade path: a database built before run_id existed must still open.
        # Fresh-database tests cannot see this — the failure is only reachable
        # on an existing box, which is every box that already ran the tool.
        old = tmp / "old.db"
        oc = sqlite3.connect(old)
        oc.executescript(
            "CREATE TABLE vault_intake_log (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts TEXT NOT NULL, src_path TEXT NOT NULL, sha256 TEXT, size INTEGER,"
            " verdict TEXT NOT NULL, action TEXT NOT NULL, dest TEXT, held_at TEXT,"
            " note TEXT);"
            "INSERT INTO vault_intake_log (ts,src_path,verdict,action)"
            " VALUES ('t','p','new','reported');")
        oc.commit()
        oc.close()
        mc = connect(old)
        assert "run_id" in {r[1] for r in mc.execute("PRAGMA table_info(vault_intake_log)")}, \
            "pre-run_id database did not migrate"
        assert mc.execute("SELECT count(*) FROM vault_intake_log").fetchone()[0] == 1, \
            "migration lost a row"
        mc.close()

        print("\nself-test OK: renamed duplicate found by bytes, archive member found "
              "inside the tarball, new file filed, incomplete download refused, "
              "0-byte file NOT mistaken for held, no duplicate destroyed.")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    pi = sub.add_parser("index", help="build the content index")
    pi.add_argument("--vault", required=True)
    pi.add_argument("--db")
    pi.add_argument("--archive-cap-mb", type=int, default=ARCHIVE_CAP // (1024 * 1024))

    ps = sub.add_parser("scan", help="reconcile a source folder against the index")
    ps.add_argument("--vault", required=True)
    ps.add_argument("--source", required=True)
    ps.add_argument("--db")
    ps.add_argument("--apply", action="store_true", help="move new items; without it, report only")

    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.cmd:
        ap.print_help()
        return 0

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"refusing: {vault} is not a directory", file=sys.stderr)
        return 2
    db = Path(args.db).expanduser() if args.db else vault / DEFAULT_DB

    if args.cmd == "index":
        return do_index(vault, db, args.archive_cap_mb * 1024 * 1024)

    source = Path(args.source).expanduser().resolve()
    if not source.is_dir():
        print(f"refusing: {source} is not a directory", file=sys.stderr)
        return 2
    return do_scan(vault, source, db, args.apply)


if __name__ == "__main__":
    sys.exit(main())
