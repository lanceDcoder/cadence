"""
=============================================================
  storage.py  —  where Cadence keeps everything
=============================================================

This is the ONLY file that knows a database exists.
Everything else just calls these functions.

THE CENTRAL IDEA: DEFINITIONS vs OCCURRENCES

  A DEFINITION is something you set up:
     - a Task    -> one thing, one day
     - a Routine -> a repeating rule ("Exercise, 7am, Mon-Fri")
     - a Goal    -> a big objective broken into sessions

  An OCCURRENCE is a thing that appears on your timeline at a
  specific date and time.

  A Task IS one occurrence.
  A Routine GENERATES an occurrence on every day it matches.
  A Goal GENERATES an occurrence per study session.

Definitions stay separate (your rule 11). Occurrences all flow
into one timeline (your rule 12). Both requirements satisfied.

Why this matters:
  "Move my exercise routine to 6pm"  -> edits the DEFINITION,
                                        every future day changes
  "Move today's exercise to 6pm"     -> edits ONE OCCURRENCE,
                                        only today changes

  Snooze only ever touches an occurrence, so it can never
  corrupt a routine. Your no-cascade rule is enforced by the
  shape of the data, not by remembering to be careful.
"""

import os
import re
import sqlite3
import threading
import uuid
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path

import config

DB_FILE = config.DATA_DIR / "cadence.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def using_postgres():
    """True when Cadence is running against Neon/PostgreSQL."""
    return bool(DATABASE_URL)


def _postgres_sql(sql):
    """Translate the small SQLite dialect used below for psycopg."""
    sql = sql.replace("?", "%s")
    sql = re.sub(r"INSERT OR IGNORE INTO", "INSERT INTO", sql,
                 flags=re.I)
    if "INSERT INTO tasks" in sql and "ON CONFLICT" not in sql and "VALUES" in sql:
        # Only routine materialisation uses INSERT OR IGNORE. Its unique
        # index makes this safe under simultaneous serverless requests.
        if "routine_id)" in sql:
            sql += " ON CONFLICT DO NOTHING"
    return sql


class _PostgresConnection:
    """Keep the existing sqlite-style storage methods portable to Neon."""
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        return self.conn.execute(_postgres_sql(sql), params or ())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        return False

    def close(self):
        self.conn.close()


# -------------------------------------------------------------
# THE SHAPE OF THE DATA
# -------------------------------------------------------------
# The CHECK lines are your product principles written into the
# database itself. Even a bug elsewhere cannot store 7:75.

SCHEMA = """
-- ========== OCCURRENCES: what appears on your timeline =======
CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT    PRIMARY KEY,
    title         TEXT    NOT NULL,
    date          TEXT    NOT NULL,
    hour          INTEGER NOT NULL CHECK (hour   BETWEEN 0 AND 23),
    minute        INTEGER NOT NULL CHECK (minute BETWEEN 0 AND 59),
    status        TEXT    NOT NULL DEFAULT 'upcoming'
                          CHECK (status IN ('upcoming', 'done', 'open')),
    remind_at     TEXT,
    snooze_count  INTEGER NOT NULL DEFAULT 0 CHECK (snooze_count >= 0),

    -- Where did this occurrence come from? NULL means you typed
    -- it in yourself as a one-off task.
    routine_id    TEXT REFERENCES routines(id) ON DELETE SET NULL,
    goal_id       TEXT REFERENCES goals(id)    ON DELETE SET NULL,
    session_note  TEXT,          -- e.g. "Week 1: Semantic HTML"

    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_date ON tasks(date);

-- ========== DEFINITION: recurring routines ===================
CREATE TABLE IF NOT EXISTS routines (
    id          TEXT    PRIMARY KEY,
    title       TEXT    NOT NULL,
    hour        INTEGER NOT NULL CHECK (hour   BETWEEN 0 AND 23),
    minute      INTEGER NOT NULL CHECK (minute BETWEEN 0 AND 59),

    -- Which days it repeats on. "0" = Monday ... "6" = Sunday.
    -- Stored as a simple comma list, e.g. "0,1,2,3,4" = Mon-Fri.
    days        TEXT    NOT NULL,

    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    start_date  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ========== DEFINITION: long-term goals ======================
CREATE TABLE IF NOT EXISTS goals (
    id          TEXT    PRIMARY KEY,
    title       TEXT    NOT NULL,
    weeks       INTEGER NOT NULL CHECK (weeks BETWEEN 1 AND 52),

    -- 'draft'    = plan made, schedule not accepted yet
    -- 'active'   = you approved it; sessions are on your timeline
    -- 'paused' / 'done'
    status      TEXT    NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft','active','paused','done')),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- The curriculum: what you study, in order.
CREATE TABLE IF NOT EXISTS goal_topics (
    id          TEXT    PRIMARY KEY,
    goal_id     TEXT    NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    week        INTEGER NOT NULL CHECK (week >= 1),
    position    INTEGER NOT NULL,
    topic       TEXT    NOT NULL,
    details     TEXT
);

CREATE INDEX IF NOT EXISTS idx_topics_goal ON goal_topics(goal_id);
"""

# PostgreSQL uses a schema per account. That preserves the original
# structural isolation: after setting search_path, queries can only see the
# signed-in person's tables, not another account's rows.
POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS routines (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    hour INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
    minute INTEGER NOT NULL CHECK (minute BETWEEN 0 AND 59),
    days TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    start_date TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    weeks INTEGER NOT NULL CHECK (weeks BETWEEN 1 AND 52),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','active','paused','done')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    date TEXT NOT NULL,
    hour INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
    minute INTEGER NOT NULL CHECK (minute BETWEEN 0 AND 59),
    status TEXT NOT NULL DEFAULT 'upcoming'
        CHECK (status IN ('upcoming', 'done', 'open')),
    remind_at TEXT,
    snooze_count INTEGER NOT NULL DEFAULT 0 CHECK (snooze_count >= 0),
    routine_id TEXT REFERENCES routines(id) ON DELETE SET NULL,
    goal_id TEXT REFERENCES goals(id) ON DELETE SET NULL,
    session_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS goal_topics (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    week INTEGER NOT NULL CHECK (week >= 1),
    position INTEGER NOT NULL,
    topic TEXT NOT NULL,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_date ON tasks(date);
CREATE INDEX IF NOT EXISTS idx_topics_goal ON goal_topics(goal_id);
CREATE INDEX IF NOT EXISTS idx_tasks_routine ON tasks(routine_id);
CREATE INDEX IF NOT EXISTS idx_tasks_goal ON tasks(goal_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_routine_day ON tasks(routine_id, date)
    WHERE routine_id IS NOT NULL;
"""


# -------------------------------------------------------------
# CONNECTING
# -------------------------------------------------------------
_local = threading.local()


def use_database(path):
    """
    Point THIS request at a particular schedule file.

    Accounts work by giving each person their own database rather
    than tagging every row with an owner. That means no query in
    this file changes, and no query can accidentally leak across
    people: two accounts are two files.

    Set per request, on the current thread only, so simultaneous
    visitors never see each other's data.
    """
    path = str(path) if using_postgres() else Path(path)
    current = getattr(_local, "path", None)
    if current is not None and current == path:
        return                      # already pointed there
    close_connection()              # drop the old one first
    _local.path = path


def current_database():
    """Which file this thread is using right now."""
    if using_postgres():
        return getattr(_local, "path", None) or "cadence_solo"
    return Path(getattr(_local, "path", None) or DB_FILE)


def close_connection():
    """Shut this thread's connection, if it has one."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _local.conn = None


def get_connection():
    """This thread's database connection, opened if needed."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        if using_postgres():
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL is configured but psycopg is missing. "
                    "Run: pip install -r requirements.txt") from exc
            raw = psycopg.connect(DATABASE_URL, row_factory=dict_row)
            conn = _PostgresConnection(raw)
            schema = current_database()
            if not re.fullmatch(r"cadence_[a-z0-9_]+", str(schema)):
                raise RuntimeError("Invalid Cadence PostgreSQL schema name.")
            conn.execute(f'SET search_path TO "{schema}", public')
            _local.conn = conn
            return conn
        conn = sqlite3.connect(current_database())
        conn.row_factory = sqlite3.Row          # rows act like dicts
        conn.execute("PRAGMA journal_mode=WAL")  # crash-safe writes
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")

        # WAL mode keeps a side-file of recent writes. Left alone it
        # grows steadily; this folds it back into the database once it
        # passes ~1 MB, so the files stay small without you doing
        # anything. (Seen in testing: a 57 KB database with a 4 MB WAL.)
        conn.execute("PRAGMA wal_autocheckpoint=256")
        _local.conn = conn
    return conn


def init_db():
    """Create tables on first run. Safe to call every start."""
    conn = get_connection()
    if using_postgres():
        schema = current_database()
        # Schema names are generated internally (cadence_<random id>) and
        # validated in get_connection before being interpolated.
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        conn.execute(f'SET search_path TO "{schema}", public')
        for statement in POSTGRES_SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute("ALTER TABLE goal_topics ADD COLUMN IF NOT EXISTS details TEXT")
        conn.conn.commit()
        return
    conn.executescript(SCHEMA)

    # If an older cadence.db exists without the new columns, add them.
    existing = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    for column, decl in [
        ("routine_id", "TEXT"),
        ("goal_id", "TEXT"),
        ("session_note", "TEXT"),
    ]:
        if column not in existing:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} {decl}")

    topic_columns = {r[1] for r in conn.execute("PRAGMA table_info(goal_topics)")}
    if "details" not in topic_columns:
        conn.execute("ALTER TABLE goal_topics ADD COLUMN details TEXT")

    # Indexes on the new columns, created only once those columns
    # definitely exist (an older cadence.db won't have had them).
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_routine "
                 "ON tasks(routine_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_goal "
                 "ON tasks(goal_id)")

    # Remove any duplicates left by the old racy code, keeping the
    # oldest row of each (routine, date) pair.
    conn.execute("""
        DELETE FROM tasks WHERE routine_id IS NOT NULL AND id NOT IN (
            SELECT MIN(id) FROM tasks WHERE routine_id IS NOT NULL
            GROUP BY routine_id, date)
    """)

    # One routine can produce at most ONE occurrence per day. Enforced
    # by the database, so two simultaneous requests cannot both insert:
    # the second simply fails and is ignored.
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uniq_routine_day
                    ON tasks(routine_id, date)
                    WHERE routine_id IS NOT NULL""")
    conn.commit()


def init_db_at(path):
    """
    Build a fresh, empty schedule at `path`, then go back to
    whatever database this thread was using.

    Used when an account is created, so the new person's file is
    ready before their first login rather than half-built during
    it.
    """
    previous = getattr(_local, "path", None)
    try:
        use_database(path)
        init_db()
    finally:
        close_connection()
        _local.path = previous


def drop_database(path):
    """Remove an account schema on PostgreSQL; used by account deletion."""
    if not using_postgres():
        return False
    schema = str(path)
    if not re.fullmatch(r"cadence_[a-z0-9_]+", schema):
        raise RuntimeError("Invalid Cadence PostgreSQL schema name.")
    close_connection()
    try:
        import psycopg
        conn = psycopg.connect(DATABASE_URL, autocommit=True)
        try:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            conn.close()
    finally:
        _local.path = None
    return True


# -------------------------------------------------------------
# ROW -> PLAIN PYTHON
# -------------------------------------------------------------
def _task(row):
    return {
        "id": row["id"], "title": row["title"], "date": row["date"],
        "hour": row["hour"], "minute": row["minute"],
        "status": row["status"], "remind_at": row["remind_at"],
        "snooze_count": row["snooze_count"],
        "routine_id": row["routine_id"], "goal_id": row["goal_id"],
        "session_note": row["session_note"],
    }


def _routine(row):
    return {
        "id": row["id"], "title": row["title"],
        "hour": row["hour"], "minute": row["minute"],
        "days": [int(d) for d in row["days"].split(",") if d != ""],
        "active": bool(row["active"]), "start_date": row["start_date"],
    }


def _goal(row):
    return {
        "id": row["id"], "title": row["title"],
        "weeks": row["weeks"], "status": row["status"],
    }


# =============================================================
#  TASKS  (occurrences)
# =============================================================
def all_tasks():
    rows = get_connection().execute(
        "SELECT * FROM tasks ORDER BY date, hour, minute").fetchall()
    return [_task(r) for r in rows]


def tasks_for_date(date):
    rows = get_connection().execute(
        "SELECT * FROM tasks WHERE date = ? ORDER BY hour, minute",
        (date,)).fetchall()
    return [_task(r) for r in rows]


def get_task(task_id):
    row = get_connection().execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _task(row) if row else None


def add_task(title, hour, minute, date, routine_id=None,
             goal_id=None, session_note=None):
    """Create one occurrence. Returns its id."""
    task_id = uuid.uuid4().hex[:8]
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO tasks (id, title, date, hour, minute, status,
                                  remind_at, snooze_count,
                                  routine_id, goal_id, session_note)
               VALUES (?,?,?,?,?, 'upcoming', NULL, 0, ?,?,?)""",
            (task_id, title, date, hour, minute,
             routine_id, goal_id, session_note))
    return task_id


def update_task(task_id, **fields):
    allowed = {"title", "date", "hour", "minute", "status",
               "remind_at", "snooze_count", "session_note"}
    changes = {k: v for k, v in fields.items() if k in allowed}
    if not changes:
        return False
    sets = ", ".join(f"{k} = ?" for k in changes)
    conn = get_connection()
    with conn:
        cur = conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?",
                           list(changes.values()) + [task_id])
    return cur.rowcount > 0


def delete_task(task_id):
    conn = get_connection()
    with conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return cur.rowcount > 0


def replace_all(tasks):
    """Wipe and re-insert. Used by tests so each starts clean."""
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM tasks")
        for t in tasks:
            conn.execute(
                """INSERT INTO tasks (id, title, date, hour, minute, status,
                                      remind_at, snooze_count,
                                      routine_id, goal_id, session_note)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (t["id"], t["title"], t["date"], t["hour"], t["minute"],
                 t.get("status", "upcoming"), t.get("remind_at"),
                 t.get("snooze_count", 0), t.get("routine_id"),
                 t.get("goal_id"), t.get("session_note")))


# =============================================================
#  ROUTINES  (definitions)
# =============================================================
def all_routines(include_paused=True):
    sql = "SELECT * FROM routines"
    if not include_paused:
        sql += " WHERE active = 1"
    sql += " ORDER BY hour, minute"
    return [_routine(r) for r in get_connection().execute(sql).fetchall()]


def get_routine(routine_id):
    row = get_connection().execute(
        "SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
    return _routine(row) if row else None


def add_routine(title, hour, minute, days, start_date):
    """days is a list like [0,1,2,3,4] for Monday-Friday."""
    rid = uuid.uuid4().hex[:8]
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO routines (id, title, hour, minute, days,
                                     active, start_date)
               VALUES (?,?,?,?,?,1,?)""",
            (rid, title, hour, minute,
             ",".join(str(d) for d in sorted(set(days))), start_date))
    return rid


def update_routine(routine_id, **fields):
    """
    Change a routine DEFINITION.

    Changing the time updates every FUTURE occurrence but leaves
    the past alone — history is a record of what happened, not
    what you later decided.
    """
    allowed = {"title", "hour", "minute", "days", "active"}
    changes = {k: v for k, v in fields.items() if k in allowed}
    if not changes:
        return False
    if "days" in changes and isinstance(changes["days"], (list, tuple)):
        changes["days"] = ",".join(str(d) for d in sorted(set(changes["days"])))
    if "active" in changes:
        changes["active"] = 1 if changes["active"] else 0

    sets = ", ".join(f"{k} = ?" for k in changes)
    conn = get_connection()
    with conn:
        cur = conn.execute(f"UPDATE routines SET {sets} WHERE id = ?",
                           list(changes.values()) + [routine_id])
    return cur.rowcount > 0


def delete_routine(routine_id, keep_past=True):
    """
    Remove a routine.

    Future occurrences go with it. Past ones stay by default —
    deleting a routine shouldn't erase your history.
    """
    today = _date.today().isoformat()
    conn = get_connection()
    with conn:
        if keep_past:
            conn.execute(
                "DELETE FROM tasks WHERE routine_id = ? AND date >= ?",
                (routine_id, today))
        else:
            conn.execute("DELETE FROM tasks WHERE routine_id = ?",
                         (routine_id,))
        cur = conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
    return cur.rowcount > 0


def drop_future_occurrences(routine_id, from_date):
    """
    Remove upcoming, unanswered occurrences of a routine.

    Used when the routine's time changes, so they can be
    regenerated. Anything you already marked done or open is
    left alone — that's your history.
    """
    conn = get_connection()
    with conn:
        conn.execute(
            """DELETE FROM tasks
               WHERE routine_id = ? AND date >= ? AND status = 'upcoming'""",
            (routine_id, from_date))


def materialise_routines(date):
    """
    Make sure this date's routine occurrences exist.

    Called whenever you look at a day. Generating on demand means
    we never have to pre-create thousands of future rows, and
    changing a routine takes effect immediately.

    Nothing is duplicated: we only add what isn't already there.
    """
    weekday = datetime.strptime(date, "%Y-%m-%d").weekday()  # Mon=0
    conn = get_connection()

    existing = {
        r["routine_id"] for r in conn.execute(
            "SELECT routine_id FROM tasks WHERE date = ? AND routine_id IS NOT NULL",
            (date,)).fetchall()
    }

    created = 0
    for routine in all_routines(include_paused=False):
        if weekday not in routine["days"]:
            continue
        if routine["id"] in existing:
            continue
        if date < routine["start_date"]:
            continue

        # Just try the insert. If another request beat us to it the
        # unique index rejects this one harmlessly. Checking first
        # and then inserting is a race: two requests both check,
        # both see nothing, and both insert.
        try:
            with conn:
                conn.execute(
                    """INSERT OR IGNORE INTO tasks
                       (id, title, date, hour, minute, status,
                        remind_at, snooze_count, routine_id)
                       VALUES (?,?,?,?,?, 'upcoming', NULL, 0, ?)""",
                    (uuid.uuid4().hex[:8], routine["title"], date,
                     routine["hour"], routine["minute"], routine["id"]))
            created += 1
        except sqlite3.IntegrityError:
            pass
    return created


# =============================================================
#  GOALS  (definitions)
# =============================================================
def all_goals():
    rows = get_connection().execute(
        "SELECT * FROM goals ORDER BY created_at DESC").fetchall()
    return [_goal(r) for r in rows]


def get_goal(goal_id):
    row = get_connection().execute(
        "SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    return _goal(row) if row else None


def add_goal(title, weeks):
    gid = uuid.uuid4().hex[:8]
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO goals (id, title, weeks, status) VALUES (?,?,?,'draft')",
            (gid, title, weeks))
    return gid


def update_goal(goal_id, **fields):
    allowed = {"title", "weeks", "status"}
    changes = {k: v for k, v in fields.items() if k in allowed}
    if not changes:
        return False
    sets = ", ".join(f"{k} = ?" for k in changes)
    conn = get_connection()
    with conn:
        cur = conn.execute(f"UPDATE goals SET {sets} WHERE id = ?",
                           list(changes.values()) + [goal_id])
    return cur.rowcount > 0


def delete_goal(goal_id):
    """Remove a goal. Its future sessions go too; past ones remain."""
    today = _date.today().isoformat()
    conn = get_connection()
    with conn:
        conn.execute(
            "DELETE FROM tasks WHERE goal_id = ? AND date >= ? AND status = 'upcoming'",
            (goal_id, today))
        cur = conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    return cur.rowcount > 0


def set_topics(goal_id, topics):
    """topics = [(week, position, title, details), ...]."""
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM goal_topics WHERE goal_id = ?", (goal_id,))
        for entry in topics:
            week, position, topic = entry[:3]
            details = entry[3] if len(entry) > 3 else None
            conn.execute(
                """INSERT INTO goal_topics (id, goal_id, week, position, topic, details)
                   VALUES (?,?,?,?,?,?)""",
                (uuid.uuid4().hex[:8], goal_id, week, position, topic, details))


def get_topics(goal_id):
    rows = get_connection().execute(
        """SELECT week, position, topic, details FROM goal_topics
           WHERE goal_id = ? ORDER BY week, position""", (goal_id,)).fetchall()
    return [{"week": r["week"], "position": r["position"], "topic": r["topic"],
             "details": r["details"]}
            for r in rows]


def goal_sessions(goal_id):
    rows = get_connection().execute(
        "SELECT * FROM tasks WHERE goal_id = ? ORDER BY date, hour, minute",
        (goal_id,)).fetchall()
    return [_task(r) for r in rows]


def goal_progress(goal_id):
    row = get_connection().execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done
           FROM tasks WHERE goal_id = ?""", (goal_id,)).fetchone()
    total = row["total"] or 0
    done = row["done"] or 0
    return {"total": total, "done": done,
            "percent": round(done / total * 100) if total else 0}


def clear_goal_sessions(goal_id, from_date):
    """Remove unanswered future sessions so a schedule can be redone."""
    conn = get_connection()
    with conn:
        conn.execute(
            """DELETE FROM tasks WHERE goal_id = ?
               AND date >= ? AND status = 'upcoming'""", (goal_id, from_date))


# =============================================================
#  LOOKING AFTER YOUR DATA
# =============================================================
def backup(destination):
    """
    Safe copy, even while the app is running.

    Copying the .db file by hand can catch it mid-write.
    SQLite's own backup cannot.
    """
    if using_postgres():
        raise RuntimeError(
            "Neon manages database durability; use Neon backups/branches "
            "instead of copying a local SQLite file.")
    dest = sqlite3.connect(destination)
    with dest:
        get_connection().backup(dest)
    dest.close()
    return destination


def integrity_check():
    if using_postgres():
        # A simple query confirms the Neon connection and account schema.
        get_connection().execute("SELECT 1").fetchone()
        return "ok"
    return get_connection().execute("PRAGMA integrity_check").fetchone()[0]


def compact():
    """
    Tidy the database files: fold the write-ahead log back in and
    reclaim unused space. Safe to run any time.
    """
    if using_postgres():
        return True
    conn = get_connection()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    return True


def stats():
    conn = get_connection()
    t = conn.execute(
        """SELECT COUNT(*) AS total, COUNT(DISTINCT date) AS days,
                  MIN(date) AS first_day, MAX(date) AS last_day
           FROM tasks""").fetchone()
    return {
        **dict(t),
        "routines": conn.execute("SELECT COUNT(*) FROM routines").fetchone()[0],
        "goals": conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0],
    }
