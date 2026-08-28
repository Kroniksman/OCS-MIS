#!/usr/bin/env bash
#
# Take a snapshot, on a schedule.
#
#   ./snapshot.sh            take one
#   ./snapshot.sh --status   when did it last run, and did it work
#
# Configured by snapshot.env beside this script (see snapshot.env.example).
# The password lives in its own file, read inside the container, so it never
# reaches the process list — this box hosts other people's sites.
#
# A snapshot that quietly stops running is the failure that matters: the MIS
# keeps answering, with figures that are three weeks old and look current.
# Every run therefore records its outcome, and --status reports the age of the
# snapshot rather than only the last exit code.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$HERE/snapshot.env"
LOG="$HERE/snapshot.log"
STATUS="$HERE/.last_run"

[ -f "$CONF" ] || { echo "missing $CONF — copy snapshot.env.example and fill it in" >&2; exit 1; }
# shellcheck disable=SC1090
. "$CONF"

: "${CW_DIR:?set CW_DIR in snapshot.env}"
: "${CW_PROJECT:?set CW_PROJECT in snapshot.env}"
: "${CW_COMPOSE:?set CW_COMPOSE in snapshot.env}"
: "${CW_DBNAME:?set CW_DBNAME in snapshot.env}"
: "${PW_FILE:=$HERE/.cw_reader_pw}"
: "${KEEP_DAYS:=7}"

status(){
  if [ ! -f "$STATUS" ]; then
    echo "never run"; exit 1
  fi
  cat "$STATUS"
  if [ -f "$HERE/cw.sqlite" ]; then
    age=$(( ( $(date +%s) - $(stat -c %Y "$HERE/cw.sqlite" 2>/dev/null || stat -f %m "$HERE/cw.sqlite") ) / 3600 ))
    echo "snapshot is ${age}h old"
    # A stale snapshot is the quiet failure. Say so in the exit code, so a
    # monitor notices without reading the text.
    [ "$age" -gt 36 ] && { echo "STALE — more than 36h since the last good snapshot"; exit 2; }
  else
    echo "no cw.sqlite present"; exit 1
  fi
  exit 0
}

[ "${1:-}" = "--status" ] && status

[ -f "$PW_FILE" ] || { echo "missing $PW_FILE" >&2; exit 1; }
perms=$(stat -c %a "$PW_FILE" 2>/dev/null || stat -f %Lp "$PW_FILE")
[ "$perms" = "600" ] || echo "warning: $PW_FILE is mode $perms, expected 600" >&2

started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "=== $started snapshot starting ===" >> "$LOG"

if (cd "$CW_DIR" && docker compose -p "$CW_PROJECT" --env-file "$CW_DIR/.env" \
        -f "$CW_COMPOSE" run --rm \
        -v "$HERE:/mis" \
        app python /mis/extract.py \
            --host db --dbname "$CW_DBNAME" --user cw_reader \
            --password-file /mis/$(basename "$PW_FILE") \
            --out /mis/cw.sqlite) >> "$LOG" 2>&1
then
    rows=$(grep -oE '^[0-9,]+ rows across' "$LOG" | tail -1 | cut -d' ' -f1)
    # Keep a dated copy. Cheap at ~600KB, and it means a snapshot taken during
    # a bad migration can be stepped back from rather than only regretted.
    cp "$HERE/cw.sqlite" "$HERE/cw-$(date -u +%Y%m%d).sqlite"
    find "$HERE" -maxdepth 1 -name 'cw-*.sqlite' -mtime +"$KEEP_DAYS" -delete
    echo "last run  $started  OK  ${rows:-?} rows" > "$STATUS"
    echo "=== ok, ${rows:-?} rows ===" >> "$LOG"
else
    echo "last run  $started  FAILED — see snapshot.log" > "$STATUS"
    echo "=== FAILED ===" >> "$LOG"
    exit 1
fi

# Keep the log from growing without bound.
tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
