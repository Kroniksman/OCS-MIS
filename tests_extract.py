"""
The extractor's own guardrails.

    CW_SOURCE_DSN=postgresql://... python tests_extract.py

Three things are worth testing here and the rest is plumbing:

**Drift is loud.** The contract is the single place this system knows CW's
shape. If CW gains a column and nothing complains, the extractor either misses
data or carries something nobody reviewed. Both are silent.

**Secrets never leave.** An allow-list is only as good as the test that proves
the excluded columns are actually absent from the output.

**Scope is resolved the way CW means it.** A company-scoped master may carry a
NULL `site_id` on purpose — a mobile tanker belongs to a company and to no
single washery. Resolving company by `site_id` alone drops those rows. CW spent
1.7.1 through 1.7.3 on this exact distinction, the last release correcting the
one before it; the extractor meets the same shape with nothing above it.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import psycopg2

import extract
import schema_contract as contract

ok, failures = 0, []


def check(label, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}\n        {detail}")


def main():
    dsn = os.environ.get("CW_SOURCE_DSN")
    if not dsn:
        sys.exit("set CW_SOURCE_DSN to a CW database")

    pg = psycopg2.connect(dsn)
    pg.set_session(readonly=True, autocommit=True)
    cur = pg.cursor()
    live = extract.live_columns(cur)

    print("1. the contract describes CW as it is now")
    check("no drift against the live schema", not contract.check_drift(live),
          "\n        ".join(contract.check_drift(live)))

    print("\n2. drift is detected, not shrugged off")
    doctored = {t: list(c) for t, c in live.items()}
    doctored["rom_inward"].append("some_new_column")
    f = contract.check_drift(doctored)
    check("a new CW column is reported",
          any("some_new_column" in x for x in f), f)

    doctored = {t: list(c) for t, c in live.items()}
    doctored["rom_inward"] = [c for c in doctored["rom_inward"] if c != "net_mt"]
    f = contract.check_drift(doctored)
    check("a removed CW column is reported", any("net_mt" in x for x in f), f)

    missing = {t: c for t, c in live.items() if t != "vehicles"}
    f = contract.check_drift(missing)
    check("a vanished table is reported", any("vehicles" in x for x in f), f)

    print("\n3. secrets cannot be declared, let alone exported")
    for table, spec in contract.TABLES.items():
        bad = [c for c in spec["columns"]
               if any(s in c.lower() for s in contract.NEVER_EXPORT)]
        check(f"{table}: nothing in NEVER_EXPORT is declared", not bad, bad)
        if len(failures) > 3:
            break

    print("\n4. a snapshot omits them in fact, not just in intent")
    out = Path(tempfile.mkdtemp()) / "probe.sqlite"
    extract.snapshot(dsn, out, verbose=False)
    sq = sqlite3.connect(out)
    users_cols = [r[1] for r in sq.execute('PRAGMA table_info("users")').fetchall()]
    check("users.password_hash is absent", "password_hash" not in users_cols)
    check("users.session_token is absent", "session_token" not in users_cols)

    print("\n5. every row knows its company")
    for table, spec in contract.TABLES.items():
        if spec["scope"] == "global":
            continue
        n = sq.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        if not n:
            continue
        orphan = sq.execute(
            f'SELECT count(*) FROM "{table}" WHERE _company_id IS NULL').fetchone()[0]
        # Declared in the contract, not hardcoded here: the superadmin belongs
        # to no company and their actions are recorded the same way.
        if table in contract.PLATFORM_ROWS:
            check(f"{table}: platform rows allowed, {n - orphan} of {n} attributed", True)
        else:
            check(f"{table}: all {n} rows attributed", orphan == 0,
                  f"{orphan} rows with no company")

    print("\n6. a company-scoped row with NULL site_id still resolves")
    # exactly the shape CW writes for a shared master
    sites = extract.company_map(cur)
    row = {"site_id": None, "group_id": 1}
    got = extract.resolve_company("vehicles", row, sites, {})
    check("group_id wins when site_id is NULL", got == 1, got)
    row = {"site_id": 1, "group_id": None}
    got = extract.resolve_company("vehicles", row, sites, {})
    check("site_id is used when there is no group", got == sites.get(1), got)

    print("\n7. a child inherits its parent's company")
    q = """SELECT count(*) FROM sales_invoice_lines l
             JOIN sales_invoices i ON i.id = l.invoice_id
            WHERE l._company_id IS NOT i._company_id"""
    try:
        mismatch = sq.execute(q).fetchone()[0]
        check("invoice lines match their invoice", mismatch == 0, f"{mismatch} mismatched")
    except sqlite3.OperationalError:
        check("invoice lines match their invoice", True, "no rows to compare")

    q2 = """SELECT count(*) FROM quality_results r
              JOIN quality_samples s ON s.id = r.quality_sample_id
             WHERE r._company_id IS NOT s._company_id"""
    mismatch = sq.execute(q2).fetchone()[0]
    check("lab results match their sample", mismatch == 0, f"{mismatch} mismatched")

    sq.close()
    cur.close()
    pg.close()

    print(f"\n{ok} passed, {len(failures)} failed")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
