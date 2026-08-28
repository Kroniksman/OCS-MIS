"""
Snapshot Coal Washery into a store the products can read.

    python extract.py --source postgresql://cw_reader:...@host/coal_washery --out cw.sqlite

**Why a snapshot and not a sync.** No CW table carries `updated_at`, and CW
hard-deletes from 36 call sites with no `deleted_at`. A consumer polling for
changes would receive new rows, miss every correction, and keep deleted rows
for ever. A full snapshot cannot be subtly wrong: whatever is in CW is what
lands, and whatever is gone is gone. At 3,496 rows — single-digit millions
after years of five washeries — that costs seconds.

**Why SQLite.** The products do their own analysis; the extractor only has to
hand them rows. One file, no server, no migration story, and every consumer can
open it with the standard library. Revisit if a single run stops fitting
comfortably in memory, not before.

**Atomicity.** The snapshot is built in a temporary file and renamed into place
only once it is complete, so a consumer never opens a half-written store and a
failed run leaves the previous one intact.

**Tenancy is the extractor's job.** A read-only connection sees every client in
the database; nothing upstream scopes it. Each row is stamped with the company
it belongs to, resolved per the rules in `schema_contract`, so a consumer
filters on one column rather than re-deriving CW's two-shaped scoping and
getting it wrong the way CW itself did three times this week.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

import schema_contract as contract


# ── CW side ───────────────────────────────────────────────────────────────────

def live_columns(cur) -> dict[str, list[str]]:
    cur.execute("""
        SELECT table_name, column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
         ORDER BY table_name, ordinal_position
    """)
    out: dict[str, list[str]] = {}
    for table, col in cur.fetchall():
        out.setdefault(table, []).append(col)
    return out


def company_map(cur) -> dict[int, int]:
    """site_id -> group_id, so a site-scoped row can name its company."""
    cur.execute("SELECT id, group_id FROM sites")
    return {sid: gid for sid, gid in cur.fetchall()}


def resolve_company(table: str, row: dict, sites: dict[int, int],
                    parents: dict[str, dict[int, int | None]]) -> int | None:
    """
    Which company does this row belong to?

    The order matters and is the whole point of doing it here once. `group_id`
    wins when present, because a company-scoped master may carry a NULL
    `site_id` on purpose — that is not missing data, it is a row that belongs to
    the company and to no single washery.
    """
    spec = contract.TABLES[table]
    scope = spec["scope"]

    if scope == "global":
        return None
    if scope.startswith("parent:"):
        ptable, fk = scope.split(":", 1)[1].split(".")
        pid = row.get(fk)
        return parents.get(ptable, {}).get(pid)
    if scope == "group_or_site":
        if row.get("group_id") is not None:
            return row["group_id"]
        return sites.get(row.get("site_id"))
    # scope == "site"
    return sites.get(row.get("site_id"))


# ── store side ────────────────────────────────────────────────────────────────

def create_table(sq: sqlite3.Connection, table: str, columns: list[str]) -> None:
    # Everything lands as TEXT/NUMERIC-agnostic: SQLite stores what it is given
    # and the products cast. Typing it here would mean tracking CW's types as
    # well as its column names, doubling the surface that drifts.
    cols = ", ".join(f'"{c}"' for c in columns)
    sq.execute(f'CREATE TABLE "{table}" ({cols}, "_company_id" INTEGER)')


def snapshot(source: str, out: Path, verbose: bool = True) -> dict:
    pg = psycopg2.connect(source)
    pg.set_session(readonly=True, autocommit=True)
    cur = pg.cursor()

    findings = contract.check_drift(live_columns(cur))
    if findings:
        print("SCHEMA DRIFT — Coal Washery no longer matches the contract:\n", file=sys.stderr)
        for f in findings:
            print(f"  {f}", file=sys.stderr)
        print("\nRefusing to snapshot. Update schema_contract.py deliberately —\n"
              "that file is the single place this system knows CW's shape.",
              file=sys.stderr)
        raise SystemExit(2)

    sites = company_map(cur)
    parents: dict[str, dict[int, int | None]] = {}
    stats: dict[str, int] = {}

    fd, tmp = tempfile.mkstemp(suffix=".sqlite", dir=str(out.parent))
    os.close(fd)
    sq = sqlite3.connect(tmp)
    try:
        # Parents before children, so a child can look up its company.
        order = sorted(contract.TABLES,
                       key=lambda t: contract.TABLES[t]["scope"].startswith("parent:"))
        for table in order:
            spec = contract.TABLES[table]
            cols = spec["columns"]
            create_table(sq, table, cols)

            cur.execute(f'SELECT {", ".join(chr(34)+c+chr(34) for c in cols)} FROM "{table}"')
            rows = cur.fetchall()
            payload, own = [], {}
            for r in rows:
                d = dict(zip(cols, r))
                cid = resolve_company(table, d, sites, parents)
                if "id" in d:
                    own[d["id"]] = cid
                payload.append([_plain(v) for v in r] + [cid])
            parents[table] = own

            sq.executemany(
                f'INSERT INTO "{table}" VALUES ({", ".join("?" * (len(cols) + 1))})',
                payload)
            stats[table] = len(payload)
            if verbose:
                print(f"  {table:22} {len(payload):>7}")

        sq.execute("CREATE TABLE _snapshot (taken_at TEXT, source TEXT, tables INTEGER, rows INTEGER)")
        sq.execute("INSERT INTO _snapshot VALUES (?,?,?,?)",
                   (datetime.now(timezone.utc).isoformat(),
                    _redact(source), len(stats), sum(stats.values())))
        for t in contract.TABLES:
            if "id" in contract.TABLES[t]["columns"]:
                sq.execute(f'CREATE INDEX "ix_{t}_company" ON "{t}" ("_company_id")')
        sq.commit()
    finally:
        sq.close()
        cur.close()
        pg.close()

    os.replace(tmp, out)          # atomic: consumers never see a partial store
    return stats


def _plain(v):
    """SQLite takes str/int/float/bytes/None; everything else becomes text."""
    if v is None or isinstance(v, (int, float, bytes, str)):
        return v
    return str(v)


def _redact(dsn: str) -> str:
    if "@" in dsn and "://" in dsn:
        head, rest = dsn.split("://", 1)
        return f"{head}://***@{rest.split('@', 1)[1]}"
    return dsn


def main() -> None:
    ap = argparse.ArgumentParser(description="Snapshot Coal Washery for the reporting products")
    ap.add_argument("--source", default=os.environ.get("CW_SOURCE_DSN"),
                    help="read-only DSN for CW's Postgres (or CW_SOURCE_DSN)")
    ap.add_argument("--out", default="cw.sqlite", help="snapshot file to write")
    ap.add_argument("--check-only", action="store_true",
                    help="verify the schema contract and exit without reading data")
    a = ap.parse_args()

    if not a.source:
        sys.exit("no source DSN — pass --source or set CW_SOURCE_DSN")

    if a.check_only:
        pg = psycopg2.connect(a.source)
        pg.set_session(readonly=True, autocommit=True)
        cur = pg.cursor()
        findings = contract.check_drift(live_columns(cur))
        cur.close(); pg.close()
        if findings:
            print("SCHEMA DRIFT:")
            for f in findings:
                print(f"  {f}")
            raise SystemExit(2)
        print("contract matches CW's schema")
        return

    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"snapshotting {_redact(a.source)} -> {out}")
    stats = snapshot(a.source, out)
    print(f"\n{sum(stats.values()):,} rows across {len(stats)} tables -> {out}")


if __name__ == "__main__":
    main()
