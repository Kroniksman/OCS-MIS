"""
Look at a snapshot and say whether it is sound.

    python verify_snapshot.py cw.sqlite

Run after any extract. It answers the questions that a row count cannot:
whether every row knows its company, whether the withheld columns really are
absent, and whether anything in the store contradicts itself.

The row counts in the extract output only prove the query ran. These check the
snapshot is usable — which is a different thing, and the one a product depends
on.
"""
import sqlite3
import sys
from pathlib import Path

import schema_contract as contract

ok, problems, notes = 0, [], []


def check(label, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        problems.append(label)
        print(f"  FAIL  {label}\n        {detail}")


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "cw.sqlite")
    if not path.exists():
        sys.exit(f"no snapshot at {path}")
    db = sqlite3.connect(path)

    taken, tables, rows = db.execute(
        "SELECT taken_at, tables, rows FROM _snapshot").fetchone()
    print(f"snapshot {path}  taken {taken}")
    print(f"{rows:,} rows across {tables} tables\n")

    print("1. the withheld columns are absent")
    for table, cols in contract._WITHHELD.items():
        present = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
        for c in cols:
            check(f"{table}.{c} is not in the snapshot", c not in present)

    print("\n2. every row knows its company")
    for table, spec in contract.TABLES.items():
        if spec["scope"] == "global":
            continue
        n = db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        if not n:
            continue
        orphan = db.execute(
            f'SELECT count(*) FROM "{table}" WHERE _company_id IS NULL').fetchone()[0]
        if table in contract.PLATFORM_ROWS:
            check(f"{table}: {n - orphan} of {n} attributed (platform rows allowed)", True)
        else:
            check(f"{table}: all {n} attributed", orphan == 0, f"{orphan} unattributed")

    print("\n3. children agree with their parents")
    for child, spec in contract.TABLES.items():
        if not spec["scope"].startswith("parent:"):
            continue
        parent, fk = spec["scope"].split(":", 1)[1].split(".")
        n = db.execute(f'SELECT count(*) FROM "{child}"').fetchone()[0]
        if not n:
            check(f"{child}: nothing to compare", True)
            continue
        bad = db.execute(f'''
            SELECT count(*) FROM "{child}" c JOIN "{parent}" p ON p.id = c."{fk}"
             WHERE c._company_id IS NOT p._company_id''').fetchone()[0]
        check(f"{child}: all {n} match their {parent}", bad == 0, f"{bad} mismatched")

    print("\n4. what the snapshot actually contains")
    companies = db.execute('''
        SELECT g.id, g.name,
               (SELECT count(*) FROM sites s WHERE s.group_id = g.id) AS washeries
          FROM site_groups g ORDER BY g.id''').fetchall()
    for cid, name, sites in companies:
        vol = db.execute(
            'SELECT count(*) FROM rom_inward WHERE _company_id = ?', (cid,)).fetchone()[0]
        print(f"     [{cid}] {name[:34]:34} {sites} washery(s), {vol} ROM receipts")
        if sites == 0:
            notes.append(f"company {cid} ({name}) has no washery — "
                         "provisioned but never completed, or its site was removed")

    if len(companies) < 2:
        notes.append("only one company in this snapshot — cross-company attribution "
                     "is untested against real data")

    print(f"\n{ok} passed, {len(problems)} failed")
    for n in notes:
        print(f"  NOTE  {n}")
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
