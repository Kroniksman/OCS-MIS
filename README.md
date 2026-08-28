# Coal Washery — extractor

Snapshots Coal Washery into a store the reporting products read.

CW is not modified and does not know this exists. See
`coal-washery-erp/docs/API_STRATEGY.md` for why this shape was chosen over an
export API inside CW.

```
   Coal Washery Postgres  --(read-only role)-->  extract.py  -->  cw.sqlite
                                                                      |
                                    consolidated MIS / AI review / trading
```

**Only this repository knows CW's schema.** Products read `cw.sqlite` and never
connect to CW. That is the whole design: CW has taken 30 migrations and will
take more, and when it moves, one file here changes and a test says so.

## Running it

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

# once, on CW's database, as an admin:
psql "$CW_ADMIN_DSN" -v pw="'...'" -f grants.sql

# either a DSN...
export CW_SOURCE_DSN="postgresql://cw_reader:...@localhost:5432/coal_washery_erp"
./venv/bin/python extract.py --out cw.sqlite

# ...or the parts separately, which is safer for a password with @ or / in it
CW_READER_PW='...' ./venv/bin/python extract.py \
    --host localhost --dbname coal_washery_erp --user cw_reader --out cw.sqlite
```

A password containing `@` silently breaks the DSN form — psycopg2 splits on the
first `@`, so `cw_reader:Cwmis@2026@db` resolves the host as `2026@db` and fails
with a name-resolution error that never mentions passwords. The DSN form now
detects that and says so; the discrete form avoids the question.

`--check-only` verifies the schema contract and exits without reading data —
cheap enough to run after every CW deploy.

## Running it against a Dockerised CW

CW's Postgres publishes no port — it is reachable only on the compose network —
so both steps run inside that network. These are the exact invocations, because
getting them wrong is quiet rather than loud.

**`-e KEY=VALUE`, never bare `-e KEY`.** `docker run` forwards a bare `-e KEY`
from the host environment; `docker compose exec` does not. With the bare form
`grants.sql` sees no password, prints its usage note and quits — having created
the role but set no password and applied no grants. The failure then surfaces
later, as an authentication error from something else.

```bash
# 1. the read-only role (idempotent — safe to re-run to reset the password)
cd /opt/coal-washery-demo
docker compose -p coal-washery-demo --env-file .env \
    -f deploy/demo/docker-compose.demo.yml \
    exec -T -e CW_READER_PW=the-password \
    db psql -U postgres -d coal_washery_demo -f - < /opt/coal-washery-extract/grants.sql
# must end with: unexpectedly_writable / (0 rows)

# 2. prove the credential before involving the extractor
docker compose -p coal-washery-demo --env-file .env \
    -f deploy/demo/docker-compose.demo.yml \
    exec -T -e PGPASSWORD=the-password \
    db psql -U cw_reader -d coal_washery_demo -c "SELECT count(*) FROM rom_inward"

# 3. the snapshot, with this repo bind-mounted into the app container
docker compose -p coal-washery-demo --env-file .env \
    -f deploy/demo/docker-compose.demo.yml \
    run --rm -v /opt/coal-washery-extract:/mis -e CW_READER_PW=the-password \
    app python /mis/extract.py \
        --host db --dbname coal_washery_demo --user cw_reader --out /mis/cw.sqlite
```

Add `--check-only` to step 3 to verify the contract without reading data — cheap
enough to run after every CW deploy.

## Running it nightly

```bash
cd /opt/coal-washery-extract
cp snapshot.env.example snapshot.env          # paths for this installation
printf 'the-password\n' > .cw_reader_pw && chmod 600 .cw_reader_pw
./snapshot.sh                                 # prove it works by hand first
./snapshot.sh --status
```

Then one line in root's crontab (`crontab -e`):

```
17 2 * * *  /opt/coal-washery-extract/snapshot.sh >/dev/null 2>&1
```

02:17 rather than 02:00 — a box with other work on it has enough jobs starting
on the hour.

**The password is in a file, not the command.** `-e CW_READER_PW=...` puts the
secret in the process list, where anything on the host can read it while the
run lasts; this box carries other people's sites. `--password-file` is read
inside the container instead.

**`--status` is the point of the whole thing.** A snapshot that quietly stops
running is worse than one that fails loudly: the MIS keeps answering, with
figures that are weeks old and look current. So status reports the *age of the
snapshot*, not merely the last exit code, and exits non-zero once it passes 36
hours — a monitor can watch it without parsing text.

    exit 0   fresh, last run succeeded
    exit 1   never run, or the snapshot file is missing
    exit 2   stale — more than 36h since the last good one

A dated copy is kept for `KEEP_DAYS` (7 by default, ~600 KB each), so a snapshot
taken during a bad migration can be stepped back from rather than only
regretted.

## What it does, and deliberately does not

**Full snapshots, not incremental sync.** No CW table carries `updated_at`, and
CW hard-deletes from 36 call sites with no `deleted_at`. A consumer polling for
changes would take new rows, miss every correction, and keep deleted rows for
ever. A snapshot cannot be subtly wrong. At 3,496 rows — single-digit millions
after years of five washeries — it costs seconds. Revisit when one run stops
being comfortable, not before.

**Every row is stamped with its company.** A read-only connection sees every
client in the database and nothing upstream scopes it, so `_company_id` is
resolved once here rather than re-derived by each product. Consumers filter on
one column.

Resolving it is not as simple as reading `site_id`. CW scopes by `site_id` *and*
`group_id`, and some rows carry a NULL `site_id` on purpose — a mobile diesel
tanker belongs to a company and to no single washery. CW spent releases 1.7.1
through 1.7.3 on that distinction, the last of them correcting the one before.
The rule lives in `schema_contract.TABLES[...]["scope"]`, per table, so it is
declared rather than guessed.

**Columns are allow-listed.** `users.password_hash` and `users.session_token`
are excluded by name, and `check_drift()` fails when any table gains a column
the contract does not declare. A deny-list would fail silently: the next
migration that adds a secret column would export it and nobody would find out.
`grants.sql` enforces the same thing at the database, where `users` is granted
column by column and no default privileges are set — so a new CW table is not
readable until somebody decides it should be.

**It never writes to CW.** Read-only at the role, and the session is opened
read-only as well. When the trading system needs to write back, that is a
different credential, a different document, and a different risk.

**The snapshot is atomic.** Built in a temporary file and renamed into place, so
a consumer never opens a half-written store and a failed run leaves the previous
one intact.

## Files

| | |
|---|---|
| `schema_contract.py` | the only place that knows CW's schema — tables, columns, scoping |
| `extract.py` | connects, checks drift, snapshots |
| `grants.sql` | the read-only role, fail-closed by construction |
| `tests_extract.py` | drift is loud, secrets stay out, scope resolves correctly |

## Tests

```bash
CW_SOURCE_DSN=... ./venv/bin/python tests_extract.py
```

They caught two modelling errors in the contract on their first run: a child
table pointed at a global parent, and the platform superadmin treated as an
unattributed row rather than a legitimate one. Both were the contract's fault,
not the extractor's, which is what the attribution check exists to surface.

## When CW changes

`extract.py` refuses to snapshot against a drifted schema. Update
`schema_contract.py` deliberately — that refusal is the feature. Regenerating
the contract wholesale from a live schema would defeat it.
