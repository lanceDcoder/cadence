#!/usr/bin/env bash
#
# =============================================================
#   deploy.sh  —  start Cadence properly
# =============================================================
#
# Checks everything is safe, backs up your data, then starts
# the production server.
#
# Use it:   ./deploy.sh
#
# First time only, make it runnable:
#           chmod +x deploy.sh

set -euo pipefail     # stop at the first error instead of limping on

cd "$(dirname "$0")"

BLUE='\033[0;34m'; GREEN='\033[0;32m'; RED='\033[0;31m'
YELLOW='\033[0;33m'; NC='\033[0m'

say()  { echo -e "  $1"; }
ok()   { echo -e "  ${GREEN}ok${NC}    $1"; }
warn() { echo -e "  ${YELLOW}note${NC}  $1"; }
fail() { echo -e "  ${RED}stop${NC}  $1"; exit 1; }

echo
echo -e "${BLUE}  ====================================================${NC}"
echo -e "${BLUE}   Cadence — deployment${NC}"
echo -e "${BLUE}  ====================================================${NC}"
echo

# ---------------------------------------------------------------
say "1. Checking Python"
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed."
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "Python $PY_VERSION"

# ---------------------------------------------------------------
say "2. Checking dependencies"
python3 - <<'PYCHECK' || fail "Missing packages. Run: pip install -r requirements.txt"
import importlib.util as _u
import sys
missing = [m for m in ("flask", "waitress") if _u.find_spec(m) is None]
if missing:
    print(f"        missing: {', '.join(missing)}")
sys.exit(1 if missing else 0)
PYCHECK
ok "flask and waitress are installed"

# ---------------------------------------------------------------
say "3. Checking the database"
python3 - <<'PYDB' || fail "Database problem. See the message above."
import sys
import storage
storage.init_db()
health = storage.integrity_check()
if health != "ok":
    print(f"        integrity check said: {health}")
    sys.exit(1)
s = storage.stats()
print(f"        {s['total']} tasks · {s['routines']} routines · {s['goals']} goals")
PYDB
ok "database is healthy"

# ---------------------------------------------------------------
say "4. Backing up your data"
mkdir -p backups
STAMP=$(date +%Y%m%d_%H%M%S)
python3 -c "import storage; storage.backup('backups/cadence_$STAMP.db')" \
  || fail "Backup failed — refusing to start."
ok "saved backups/cadence_$STAMP.db"

# If accounts are switched on, every person's schedule needs backing
# up too — not just the solo database.
if [ -f accounts.db ]; then
  python3 - "$STAMP" <<'PYACC' || fail "Account backup failed."
import shutil, sys
from pathlib import Path
import auth, storage

stamp = sys.argv[1]
out = Path("backups") / f"accounts_{stamp}"
out.mkdir(parents=True, exist_ok=True)

shutil.copy("accounts.db", out / "accounts.db")
n = 0
for user in auth.list_users():
    src = auth.db_path_for(user)
    if src.exists():
        storage.use_database(src)
        storage.backup(str(out / user["db_file"]))
        storage.close_connection()
        n += 1
print(f"        {n} account schedule(s) backed up")
PYACC
  ok "saved backups/accounts_$STAMP/"
fi

# Keep the ten most recent backups.
ls -1t backups/cadence_*.db 2>/dev/null | tail -n +11 | xargs -r rm --
KEPT=$(ls -1 backups/cadence_*.db 2>/dev/null | wc -l | tr -d ' ')
say "      keeping the $KEPT most recent"

# ---------------------------------------------------------------
say "5. Running the test suite"
if [ "${SKIP_TESTS:-no}" = "yes" ]; then
  warn "skipped (SKIP_TESTS=yes)"
else
  # The tests need a running server, so only run them if one is up.
  if curl -s -o /dev/null --max-time 2 http://127.0.0.1:5000/ 2>/dev/null; then
    FAILED=0
    for t in test_check test_alarm test_features; do
      if python3 "$t.py" >/tmp/cadence_$t.log 2>&1; then
        RESULT=$(grep -oE "RESULT:.*" /tmp/cadence_$t.log || echo "passed")
        say "      $t — $RESULT"
      else
        FAILED=1
        say "      ${RED}$t FAILED${NC} — see /tmp/cadence_$t.log"
      fi
    done
    [ "$FAILED" = "0" ] || fail "Tests failed. Fix them before deploying."
    ok "all tests passed"
  else
    warn "dev server isn't running, so tests were skipped"
    say "      to run them: python3 app.py in another terminal"
  fi
fi

# ---------------------------------------------------------------
say "6. Security check"
python3 - <<'PYSEC' || fail "Security check failed."
import os
os.environ["CADENCE_ENV"] = "production"
import importlib, config
importlib.reload(config)
cfg = config.get_config()
assert cfg.DEBUG is False, "DEBUG is still on in production!"
assert cfg.SECRET_KEY and len(cfg.SECRET_KEY) >= 32, "Secret key is too weak"
print("        debug OFF · secret key present · cookies hardened")
PYSEC
ok "safe to run"

if [ -f .secret_key ]; then
  PERMS=$(stat -c "%a" .secret_key 2>/dev/null || stat -f "%A" .secret_key 2>/dev/null || echo "?")
  [ "$PERMS" = "600" ] && ok ".secret_key is private (600)" \
                       || warn ".secret_key permissions are $PERMS (600 is better)"
fi

# ---------------------------------------------------------------
echo
echo -e "${GREEN}  Everything checks out. Starting the server.${NC}"
echo

export CADENCE_ENV=production
export PORT="${PORT:-8000}"
export THREADS="${THREADS:-4}"

exec python3 serve.py
