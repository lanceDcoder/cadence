"""
=============================================================
  auth.py  —  optional user accounts
=============================================================

ACCOUNTS ARE OFF BY DEFAULT.

Cadence was designed as a single-user personal tool and it still
behaves exactly that way out of the box: open it, your schedule
is there, no login. Nothing in this file runs unless you turn it
on.

TO TURN IT ON
    CADENCE_ACCOUNTS=on python3 app.py

To turn it off again, remove that and restart. Your data is
untouched either way.


HOW ISOLATION WORKS  (the important bit)

The usual way to support several people is one shared database
with an `owner_id` column on every table, and `WHERE owner_id=?`
on every query. Cadence has 38 SQL statements. Forget that clause
in ONE of them and somebody silently sees another person's
schedule. Nothing crashes. Nothing warns you.

So Cadence does it differently: **each account gets its own
database file.**

    cadence.db              <- the solo file (accounts off)
    users/cadence_a1b2.db   <- Ade's schedule
    users/cadence_c3d4.db   <- Sarah's schedule

Two people cannot see each other's tasks for the same reason you
cannot read a file that was never opened. The isolation is
structural, not a rule somebody has to remember.

What this costs: you cannot write one query spanning all users.
Cadence never needs to.


WHERE PASSWORDS LIVE

Accounts sit in their own file, `accounts.db`, apart from every
schedule. Passwords are never stored — only a scrypt hash, via
werkzeug, which ships with Flask. No extra package needed.

Deleting an account deletes the row here AND that person's
database file.
"""

import os
import re
import sqlite3
import uuid
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

import config

ACCOUNTS_DB = config.DATA_DIR / "accounts.db"
USER_DATA_DIR = config.DATA_DIR / "users"

MIN_PASSWORD = 8
MAX_PASSWORD = 200          # scrypt is slow by design; cap the input
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")

ACCOUNTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    db_file       TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0,1)),
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_login    TEXT
);

CREATE TABLE IF NOT EXISTS auth_attempts (
    key           TEXT PRIMARY KEY,
    window_start  INTEGER NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0
);
"""


# -------------------------------------------------------------
# IS THIS FEATURE ON?
# -------------------------------------------------------------
def is_enabled():
    """
    Accounts are opt-in. Anything other than an explicit yes
    means the app stays single-user, exactly as before.
    """
    return os.environ.get("CADENCE_ACCOUNTS", "").strip().lower() in (
        "on", "1", "true", "yes", "enabled")


def allow_signup():
    """
    Can a visitor create their own account?

    Default NO — even with accounts on. Otherwise anyone who finds
    the address can register. The owner makes accounts with:

        python3 manage_users.py add <name>
    """
    return os.environ.get("CADENCE_SIGNUP", "").strip().lower() in (
        "on", "1", "true", "yes", "open")


# -------------------------------------------------------------
# CONNECTING
# -------------------------------------------------------------
def _connect():
    conn = sqlite3.connect(ACCOUNTS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_accounts():
    """Create the accounts file and the per-user data folder."""
    USER_DATA_DIR.mkdir(exist_ok=True)
    conn = _connect()
    with conn:
        conn.executescript(ACCOUNTS_SCHEMA)
        conn.execute("DELETE FROM auth_attempts WHERE window_start < strftime('%s','now') - 86400")
    conn.close()

    # Keep the folder private on Unix. Windows ignores this.
    try:
        os.chmod(USER_DATA_DIR, 0o700)
        if ACCOUNTS_DB.exists():
            os.chmod(ACCOUNTS_DB, 0o600)
    except OSError:
        pass


def _row_to_user(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "db_file": row["db_file"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
        "last_login": row["last_login"],
    }


# -------------------------------------------------------------
# ABUSE CONTROLS
# -------------------------------------------------------------
def rate_limit(key, limit=10, window_seconds=900):
    """Return True when a key has exceeded the attempt limit."""
    import time
    now_ts = int(time.time())
    conn = _connect()
    try:
        with conn:
            row = conn.execute(
                "SELECT window_start, attempts FROM auth_attempts WHERE key = ?",
                (key,)).fetchone()
            if not row or now_ts - row["window_start"] >= window_seconds:
                conn.execute(
                    "INSERT INTO auth_attempts(key, window_start, attempts) VALUES(?,?,1) "
                    "ON CONFLICT(key) DO UPDATE SET window_start=excluded.window_start, attempts=1",
                    (key, now_ts))
                return False
            if row["attempts"] >= limit:
                return True
            conn.execute("UPDATE auth_attempts SET attempts = attempts + 1 WHERE key = ?", (key,))
            return False
    finally:
        conn.close()

def clear_rate_limit(key):
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM auth_attempts WHERE key = ?", (key,))
    finally:
        conn.close()

# -------------------------------------------------------------
# VALIDATION
# -------------------------------------------------------------
def check_username(username):
    """Returns None if fine, or a plain-English complaint."""
    if not isinstance(username, str) or not username.strip():
        return "Pick a username."
    username = username.strip()
    if not USERNAME_RE.match(username):
        return ("Usernames can use letters, numbers, hyphens and "
                "underscores, 3 to 32 characters.")
    return None


def check_password(password):
    """Returns None if fine, or a plain-English complaint."""
    if not isinstance(password, str) or not password:
        return "Pick a password."
    if len(password) < MIN_PASSWORD:
        return f"Passwords need at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return f"That password is too long (max {MAX_PASSWORD})."
    return None


# -------------------------------------------------------------
# ACCOUNTS
# -------------------------------------------------------------
def count_users():
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def list_users():
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at").fetchall()
        return [_row_to_user(r) for r in rows]
    finally:
        conn.close()


def get_user(user_id):
    conn = _connect()
    try:
        return _row_to_user(conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
    finally:
        conn.close()


def get_by_username(username):
    conn = _connect()
    try:
        return _row_to_user(conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            ((username or "").strip(),)).fetchone())
    finally:
        conn.close()


def create_user(username, password, display_name=None, is_admin=False):
    """
    Make an account and its private database file.

    Returns (user_dict, None) or (None, "what went wrong").
    """
    problem = check_username(username) or check_password(password)
    if problem:
        return None, problem

    username = username.strip()
    if get_by_username(username):
        return None, f"The name '{username}' is taken."

    init_accounts()

    # The very first account is always the owner. Keeping this rule
    # here — rather than in each caller — means a new caller cannot
    # forget it and leave a system with no owner at all.
    if count_users() == 0:
        is_admin = True

    user_id = uuid.uuid4().hex[:12]
    db_file = f"cadence_{user_id}.db"

    conn = _connect()
    try:
        with conn:
            conn.execute(
                """INSERT INTO users (id, username, display_name,
                                      password_hash, db_file, is_admin)
                   VALUES (?,?,?,?,?,?)""",
                (user_id, username, (display_name or username).strip()[:60],
                 generate_password_hash(password), db_file,
                 1 if is_admin else 0))
    except sqlite3.IntegrityError:
        # Someone claimed the name between the check and the insert.
        return None, f"The name '{username}' is taken."
    finally:
        conn.close()

    # Build their empty schedule immediately, so first login isn't
    # the moment we discover the folder isn't writable. If database
    # creation fails, roll the account row back too; otherwise we'd
    # leave a login that can never reach its own data.
    import storage
    try:
        storage.init_db_at(USER_DATA_DIR / db_file)
    except Exception:
        cleanup = _connect()
        try:
            with cleanup:
                cleanup.execute("DELETE FROM users WHERE id = ?", (user_id,))
        finally:
            cleanup.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                (USER_DATA_DIR / (db_file + suffix)).unlink()
            except FileNotFoundError:
                pass
        raise

    return get_user(user_id), None


def verify(username, password):
    """
    Check a login.

    Returns (user_dict, None) or (None, message).
    The message is deliberately vague — saying "no such user"
    tells an attacker which names exist.
    """
    user = get_by_username(username)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ? COLLATE NOCASE",
            ((username or "").strip(),)).fetchone()
    finally:
        conn.close()

    if not user or not row:
        # Hash anyway, so a missing user doesn't answer faster than
        # a wrong password. Timing differences leak which names exist.
        generate_password_hash("dummy-timing-equaliser")
        return None, "That username and password don't match."

    if not check_password_hash(row["password_hash"], password or ""):
        return None, "That username and password don't match."

    touch_login(user["id"])
    return user, None


def touch_login(user_id):
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "UPDATE users SET last_login = datetime('now') WHERE id = ?",
                (user_id,))
    finally:
        conn.close()


def set_password(user_id, password):
    problem = check_password(password)
    if problem:
        return problem
    conn = _connect()
    try:
        with conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                         (generate_password_hash(password), user_id))
    finally:
        conn.close()
    return None


def delete_user(user_id, remove_data=True):
    """
    Remove an account. By default their schedule file goes too.

    Pass remove_data=False to keep the file, e.g. before handing
    it to someone else.
    """
    user = get_user(user_id)
    if not user:
        return "No such account."

    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    finally:
        conn.close()

    if remove_data:
        # The current request may still have this person's SQLite file
        # open. Windows does not permit deleting an open database file,
        # so release this thread's storage connection before unlinking it.
        import storage
        storage.close_connection()
        for suffix in ("", "-wal", "-shm"):
            path = USER_DATA_DIR / (user["db_file"] + suffix)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
    return None


def db_path_for(user):
    """Where this person's schedule lives."""
    return USER_DATA_DIR / user["db_file"]
