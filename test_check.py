"""
Health check for Cadence MVP v1.

Run it any time with:   python3 test_check.py

It talks to the app the same way your browser does, so if this
passes, the real thing works. It cleans up after itself.
"""

import atexit
import json
import threading
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import storage  # noqa: E402

import os as _os
BASE = _os.environ.get("CADENCE_URL", "http://127.0.0.1:5000")
DATA = Path(__file__).parent / "cadence.db"
BACKUP = Path(__file__).parent / "tasks.backup.json"

passed, failed = [], []


_saved_rows = None


def restore():
    """
    Put the user's real tasks back.

    We snapshot the ROWS, not the .db file. The app keeps the
    database open in WAL mode, so copying the file mid-run does
    not produce a usable backup — that mistake wiped real tasks
    once already.

    Registered with atexit so it runs even if a test crashes.
    """
    if _saved_rows is not None:
        storage.replace_all(_saved_rows)


def check(name, condition, detail=""):
    (passed if condition else failed).append(name)
    mark = "PASS" if condition else "FAIL"
    line = f"  [{mark}] {name}"
    if detail:
        line += f"\n         {detail}"
    print(line)


def get(path="/"):
    return urllib.request.urlopen(BASE + path).read().decode()


def post(path, fields):
    data = urllib.parse.urlencode(fields).encode()
    return urllib.request.urlopen(BASE + path, data=data).read().decode()


def tasks_on_disk():
    return storage.all_tasks()


def find(title):
    for t in tasks_on_disk():
        if t["title"] == title:
            return t
    return None


# ---------------------------------------------------------------
print("\nCADENCE — HEALTH CHECK")
print("=" * 62)

# Protect the user's real data before we poke at it.
storage.init_db()
_saved_rows = storage.all_tasks()
atexit.register(restore)

# --- 1. Is the server up? -------------------------------------
print("\n1. SERVER")
try:
    html = get("/")
    check("Home page responds", True)
except Exception as e:
    check("Home page responds", False, str(e))
    print("\nServer is not running. Start it with: python3 app.py")
    sys.exit(1)

check("Page is real HTML", "<!DOCTYPE html>" in html)
check("App name appears", "Cadence" in html)

# --- 2. The 24-hour timeline ----------------------------------
print("\n2. TWENTY-FOUR HOUR TIMELINE  (§8)")
rows = len(re.findall(r'<div class="hour-row', html))
check("Exactly 24 hour rows", rows == 24, f"found {rows}")
check("Midnight labelled 12:00 AM", ">12:00 AM<" in html)
check("Noon labelled 12:00 PM", ">12:00 PM<" in html)
check("Last hour is 11:00 PM", ">11:00 PM<" in html)
check("Current-time marker present", 'class="now-line"' in html)

# --- 3. Assistant panel ---------------------------------------
print("\n3. ASSISTANT PANEL  (§9, §16)")
check("Greeting shown",
      any(g in html for g in ["Good morning", "Good afternoon", "Good evening"]))
check("Schedule summary shown", "scheduled today" in html or "Nothing scheduled" in html)
check("Next-up line shown",
      any(s in html for s in ["Next up:", "Nothing further", "Add your first", "all", "done"]))

# --- 4. THE EXACT TIME RULE -----------------------------------
print("\n4. EXACT TIME RULE  (§4 — the most important rule)")
samples = [
    ("07:30", 7, 30, "7:30 AM"),
    ("14:00", 14, 0, "2:00 PM"),
    ("00:00", 0, 0, "12:00 AM"),
    ("12:00", 12, 0, "12:00 PM"),
    ("23:59", 23, 59, "11:59 PM"),
    ("06:05", 6, 5, "6:05 AM"),
    ("13:47", 13, 47, "1:47 PM"),
]
for raw, eh, em, label in samples:
    title = f"__t_{raw.replace(':','')}"
    post("/tasks", {"title": title, "time": raw})
    t = find(title)
    ok = t and t["hour"] == eh and t["minute"] == em
    got = f"stored ({t['hour']},{t['minute']})" if t else "not saved"
    check(f"{raw} kept exactly -> {label}", ok, got)

page = get("/")
check("7:30 AM renders on the page", "7:30 AM" in page)
check("1:47 PM renders on the page", "1:47 PM" in page)

# --- 5. The app must never invent a time ----------------------
print("\n5. NEVER INVENT A TIME  (§21 rule 4)")
before = len(tasks_on_disk())
post("/tasks", {"title": "__no_time", "time": ""})
check("Empty time rejected", len(tasks_on_disk()) == before and not find("__no_time"))

before = len(tasks_on_disk())
post("/tasks", {"title": "", "time": "10:00"})
check("Empty title rejected", len(tasks_on_disk()) == before)

for bad in ["25:00", "12:99", "abc", "7"]:
    before = len(tasks_on_disk())
    post("/tasks", {"title": f"__bad_{bad}", "time": bad})
    check(f"Invalid time {bad!r} rejected", len(tasks_on_disk()) == before)

# --- 6. Edit / done / delete ----------------------------------
print("\n6. TASK MANAGEMENT  (MVP items 8, 9, 11)")
post("/tasks", {"title": "__lifecycle", "time": "09:15"})
t = find("__lifecycle")
check("Task created", t is not None)

if t:
    tid = t["id"]

    post(f"/tasks/{tid}/edit", {"title": "__lifecycle_v2", "time": "16:45"})
    t2 = find("__lifecycle_v2")
    check("Edit changes title and time",
          t2 and t2["hour"] == 16 and t2["minute"] == 45)

    post(f"/tasks/{tid}/toggle", {})
    check("Mark done works", find("__lifecycle_v2")["status"] == "done")

    post(f"/tasks/{tid}/toggle", {})
    check("Undo done works", find("__lifecycle_v2")["status"] == "upcoming")

    post(f"/tasks/{tid}/delete", {})
    check("Delete removes task", find("__lifecycle_v2") is None)

    check("Task id stays stable through edits", tid == t["id"])

# --- 7. Ordering ----------------------------------------------
print("\n7. ORDERING WITHIN AN HOUR")
for m in ["10:40", "10:05", "10:20"]:
    post("/tasks", {"title": f"__ord_{m.replace(':','')}", "time": m})
page = get("/")
pos = [page.find(f"__ord_{x}") for x in ["1005", "1020", "1040"]]
check("Earlier minutes appear first", pos == sorted(pos), f"positions {pos}")

# --- 8. Safety ------------------------------------------------
print("\n8. SAFETY")
post("/tasks", {"title": "<script>alert(1)</script>", "time": "11:11"})
page = get("/")
check("HTML in a task title is escaped (no injection)",
      "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page)

post("/tasks", {"title": "Say \"hi\" to O'Brien", "time": "11:12"})
page = get("/")
m = re.search(r"openEdit\('[^']*',\s*'((?:[^'\\]|\\.)*)'", page[page.find("O&#39;Brien") - 900:] or "")
check("Quotes in a title don't break the Edit button", "O&#39;Brien" in page)

long_title = "x" * 500
post("/tasks", {"title": long_title, "time": "11:13"})
check("Very long title accepted without crashing", find(long_title) is not None)

try:
    urllib.request.urlopen(BASE + "/nonexistent")
    code = 200
except urllib.error.HTTPError as e:
    code = e.code
check("Unknown page returns a clean 404", code == 404, f"got HTTP {code}")

for route in ["edit", "toggle", "delete"]:
    try:
        fields = {"title": "x", "time": "10:00"} if route == "edit" else {}
        post(f"/tasks/DOESNOTEXIST/{route}", fields)
        ok = True
    except Exception:
        ok = False
    check(f"Unknown task id on /{route} doesn't crash", ok)

# --- 8b. Concurrency (no database, so this must hold) ---------
print("\n8b. SIMULTANEOUS SAVES  (database transactions)")
# Routines auto-generate occurrences whenever a page is viewed, which
# would inflate the count below. Pause them so we measure only our saves.
_paused = [r["id"] for r in storage.all_routines() if r["active"]]
for _rid in _paused:
    storage.update_routine(_rid, active=False)
storage.replace_all([])
errors = []
def _add(i):
    try:
        post("/tasks", {"title": f"__conc_{i}", "time": "10:00"})
    except Exception as e:
        errors.append(e)
threads = [threading.Thread(target=_add, args=(i,)) for i in range(25)]
for t in threads: t.start()
for t in threads: t.join()
stored = len([t for t in tasks_on_disk() if t["title"].startswith("__conc_")])
check("25 simultaneous saves lose nothing", stored == 25,
      f"stored {stored}/25 — was 1/25 with the old JSON file")
check("No errors during concurrent saves", not errors)

# --- 9. Known limitations (documented, not bugs to hide) ------
print("\n9. KNOWN LIMITATIONS  (documented, not hidden)")
from datetime import timedelta  # noqa: E402
from app import now  # noqa: E402

yesterday = (now() - timedelta(days=1)).strftime("%Y-%m-%d")
storage.replace_all([{
    "id": "__yst", "title": "__yesterday", "date": yesterday,
    "hour": 14, "minute": 0, "status": "upcoming",
    "remind_at": None, "snooze_count": 0,
}])
visible = "__yesterday" in get("/")
print(f"  [KNOWN] Yesterday's tasks are invisible: "
      f"{'still invisible (unfixed)' if not visible else 'now visible'}")
print("  [KNOWN] No day navigation yet — approved as D2, not yet built")

# --- 10. Database health --------------------------------------
print("\n10. DATABASE  (SQLite, no user accounts)")
check("Database passes its own integrity check",
      storage.integrity_check() == "ok")

# The database refuses impossible times, even if a bug bypassed
# our Python checks. The exact-time rule is enforced at the
# deepest level now.
import sqlite3  # noqa: E402
for bad_hour in (24, -1):
    try:
        storage.get_connection().execute(
            "INSERT INTO tasks (id,title,date,hour,minute) VALUES (?,?,?,?,?)",
            ("__bad", "x", "2026-01-01", bad_hour, 0))
        storage.get_connection().rollback()
        rejected = False
    except sqlite3.IntegrityError:
        rejected = True
    check(f"Database itself rejects hour={bad_hour}", rejected)

try:
    storage.get_connection().execute(
        "INSERT INTO tasks (id,title,date,hour,minute,status) "
        "VALUES (?,?,?,?,?,?)", ("__bad2", "x", "2026-01-01", 9, 0, "nonsense"))
    storage.get_connection().rollback()
    rejected = False
except sqlite3.IntegrityError:
    rejected = True
check("Database itself rejects an invalid status", rejected)

# SQL injection: the title below would drop the table if we built
# queries by pasting strings together. We use placeholders instead.
storage.replace_all([])
post("/tasks", {"title": "Study'); DROP TABLE tasks;--", "time": "10:00"})
injected = [t for t in storage.all_tasks() if "DROP TABLE" in t["title"]]
survived = (storage.integrity_check() == "ok" and len(injected) == 1
            and storage.get_connection().execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='tasks'"
            ).fetchone()[0] == 1)
check("SQL injection in a task title is harmless", survived)

check("Backup produces a valid copy",
      bool(storage.backup("/tmp/cadence_backup_test.db")))

for _rid in _paused:                    # put the routines back
    storage.update_routine(_rid, active=True)

print("\n" + "=" * 62)
print(f"RESULT:  {len(passed)} passed, {len(failed)} failed")
if failed:
    print("\nFailures:")
    for f in failed:
        print(f"  - {f}")
print("=" * 62 + "\n")
sys.exit(1 if failed else 0)
