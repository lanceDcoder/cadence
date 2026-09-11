"""
Alarm tests for Cadence — Phases 8 & 9.

Checks the half of the core loop that was missing:
    ALARM  ->  USER RESPONSE  (Done / Not done yet / Snooze)

Run with:   python3 test_alarm.py
"""

import atexit
import json
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import os as _os
BASE = _os.environ.get("CADENCE_URL", "http://127.0.0.1:5000")
DATA = Path(__file__).parent / "cadence.db"
BACKUP = Path(__file__).parent / "tasks.alarmbackup.json"

sys.path.insert(0, str(Path(__file__).parent))
import storage  # noqa: E402
from app import now, today_str  # noqa: E402

passed, failed = [], []


def check(name, ok, detail=""):
    (passed if ok else failed).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"\n         {detail}" if detail else ""))


def get_json(path):
    return json.loads(urllib.request.urlopen(BASE + path).read().decode())


def post_json(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        return json.loads(urllib.request.urlopen(req).read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code}


def write(tasks):
    storage.replace_all(tasks)


def read():
    return storage.all_tasks()


def one(task_id):
    """
    The specific task, by id.

    Never use read()[0]: routines auto-generate occurrences when a
    page is viewed, and one of those can sort ahead of the task we
    are actually testing.
    """
    return storage.get_task(task_id)


def task(tid, title, hour, minute, status="upcoming", remind_at=None, snoozes=0):
    return {"id": tid, "title": title, "date": today_str(), "hour": hour,
            "minute": minute, "status": status, "remind_at": remind_at,
            "snooze_count": snoozes}


def hhmm(offset_minutes):
    """A time offset from now, as (hour, minute)."""
    total = now().hour * 60 + now().minute + offset_minutes
    total = max(0, min(total, 23 * 60 + 59))
    return total // 60, total % 60


print("\nCADENCE — ALARM TESTS  (Phases 8 & 9)")
print("=" * 62)

_saved_rows = None


def restore():
    """
    Put the user's real tasks back.

    Snapshots the ROWS, not the .db file: the app holds the
    database open in WAL mode, so a file copy is not a valid
    backup. Runs even if a test crashes.
    """
    if _saved_rows is not None:
        storage.replace_all(_saved_rows)


storage.init_db()
_saved_rows = storage.all_tasks()
atexit.register(restore)

# ---------------------------------------------------------------
print("\n1. DOES THE ALARM FIRE AT THE RIGHT MOMENT?  (§2)")

ph, pm = hhmm(-1)      # one minute ago -> should be ringing
fh, fm = hhmm(+90)     # 90 minutes away -> should not
write([task("past001", "Finish assignment", ph, pm),
       task("futr001", "Call Sarah", fh, fm)])

due = get_json("/api/due")["task"]
check("A task whose time has arrived rings",
      due and due["id"] == "past001", f"got {due['id'] if due else None}")
check("A future task does not ring", not (due and due["id"] == "futr001"))
check("Alarm reports the planned time",
      due and due["time_label"].endswith(("AM", "PM")),
      f"label = {due['time_label'] if due else None}")

write([task("futr001", "Call Sarah", fh, fm)])
check("Nothing rings when nothing is due", get_json("/api/due")["task"] is None)

# ---------------------------------------------------------------
print("\n2. ONE ALARM AT A TIME, EARLIEST FIRST")

a_h, a_m = hhmm(-30)
b_h, b_m = hhmm(-10)
write([task("late002", "Later overdue", b_h, b_m),
       task("erly002", "Earlier overdue", a_h, a_m)])
due = get_json("/api/due")["task"]
check("Earliest overdue task rings first",
      due and due["id"] == "erly002", f"got {due['id'] if due else None}")

# ---------------------------------------------------------------
print("\n3. DONE")

write([task("done003", "Finish assignment", ph, pm)])
res = post_json("/tasks/done003/respond", {"action": "done"})
saved = one("done003")
check("Done is accepted", res.get("ok") is True)
check("Status becomes 'done'", saved["status"] == "done")
check("A done task stops ringing", get_json("/api/due")["task"] is None)
check("Planned time is unchanged by Done",
      saved["hour"] == ph and saved["minute"] == pm)

# ---------------------------------------------------------------
print("\n4. NOT DONE YET  ->  'still open'  (§21 supportive)")

write([task("open004", "Finish assignment", ph, pm)])
post_json("/tasks/open004/respond", {"action": "open"})
saved = one("open004")
check("Status becomes 'open'", saved["status"] == "open")
check("It stops ringing (no nagging)", get_json("/api/due")["task"] is None)
check("Planned time is unchanged", saved["hour"] == ph and saved["minute"] == pm)

page = urllib.request.urlopen(BASE + "/").read().decode()
check("Shows 'still open' on the timeline", "still open" in page)
check("No punitive wording used",
      not any(w in page.lower() for w in ["failed", "overdue!", "you missed"]))

# ---------------------------------------------------------------
print("\n5. SNOOZE  —  THE MOST IMPORTANT RULES  (§3, §4)")

write([task("snoz005", "Study", ph, pm)])
before = one("snoz005")
post_json("/tasks/snoz005/respond", {"action": "snooze"})
after = one("snoz005")

check("PLANNED TIME IS NOT CHANGED BY SNOOZE  (§4)",
      after["hour"] == before["hour"] and after["minute"] == before["minute"],
      f"was {before['hour']}:{before['minute']:02d}, "
      f"now {after['hour']}:{after['minute']:02d}")
check("A separate reminder time is set", after["remind_at"] is not None,
      f"remind_at = {after['remind_at']}")

rh, rm = map(int, after["remind_at"].split(":"))
expected = (now().hour * 60 + now().minute) + 10
check("Reminder is 10 minutes from now",
      abs((rh * 60 + rm) - expected) <= 1,
      f"remind_at = {after['remind_at']}")
check("Snooze count increments", after["snooze_count"] == 1)
check("It stops ringing immediately", get_json("/api/due")["task"] is None)
check("Still 'upcoming', not done", after["status"] == "upcoming")

page = urllib.request.urlopen(BASE + "/").read().decode()
check("Timeline still shows the PLANNED time",
      f"{before['hour'] % 12 or 12}:{before['minute']:02d}" in page)

# ---------------------------------------------------------------
print("\n6. SNOOZE MUST NOT MOVE OTHER TASKS  (§3 — no cascade)")

s_h, s_m = hhmm(-1)
write([
    task("cascA", "Study", s_h, s_m),
    task("cascB", "Grocery shopping", 15, 0),
    task("cascC", "Call Sarah", 16, 0),
])
post_json("/tasks/cascA/respond", {"action": "snooze"})
after = {t["id"]: t for t in read()}

check("Other task B stays at its exact time",
      after["cascB"]["hour"] == 15 and after["cascB"]["minute"] == 0,
      f"B is at {after['cascB']['hour']}:{after['cascB']['minute']:02d}")
check("Other task C stays at its exact time",
      after["cascC"]["hour"] == 16 and after["cascC"]["minute"] == 0,
      f"C is at {after['cascC']['hour']}:{after['cascC']['minute']:02d}")
check("Other tasks get no reminder override",
      after["cascB"]["remind_at"] is None and after["cascC"]["remind_at"] is None)
check("Snoozed task keeps its own planned time",
      after["cascA"]["hour"] == s_h and after["cascA"]["minute"] == s_m)

# ---------------------------------------------------------------
print("\n7. SNOOZING REPEATEDLY")

write([task("rep007", "Study", ph, pm)])
for i in range(1, 4):
    # Pretend the snooze already elapsed so it can ring again.
    storage.update_task("rep007", remind_at=f"{ph:02d}:{pm:02d}")
    post_json("/tasks/rep007/respond", {"action": "snooze"})

final = one("rep007")
check("Snooze count reaches 3", final["snooze_count"] == 3,
      f"count = {final['snooze_count']}")
check("Planned time STILL unchanged after 3 snoozes",
      final["hour"] == ph and final["minute"] == pm,
      f"still {final['hour']}:{final['minute']:02d} — intention preserved")

# ---------------------------------------------------------------
print("\n8. EDITING CLEARS A SNOOZE")

write([task("edit008", "Study", ph, pm, remind_at="23:00", snoozes=2)])
urllib.request.urlopen(
    BASE + "/tasks/edit008/edit",
    data=urllib.parse.urlencode({"title": "Study revised", "time": "20:15"}).encode(),
)
saved = one("edit008")
check("New time is stored exactly",
      saved["hour"] == 20 and saved["minute"] == 15)
check("Old snooze is cleared", saved["remind_at"] is None)
check("Snooze count resets", saved["snooze_count"] == 0)

write([task("edit009", "Study", ph, pm, status="open")])
urllib.request.urlopen(
    BASE + "/tasks/edit009/edit",
    data=urllib.parse.urlencode({"title": "Study", "time": "21:30"}).encode(),
)
check("Giving an 'open' task a new time makes it live again",
      one("edit009")["status"] == "upcoming")

# ---------------------------------------------------------------
print("\n9. BAD INPUT DOESN'T CRASH ANYTHING")

write([task("bad010", "Study", ph, pm)])
r = post_json("/tasks/bad010/respond", {"action": "nonsense"})
check("Unknown action is rejected", r.get("ok") is False)
r = post_json("/tasks/NOSUCHID/respond", {"action": "done"})
check("Unknown task id returns not-found", r.get("ok") is False)
check("Server still healthy afterwards", get_json("/api/due") is not None)

# ---------------------------------------------------------------
print("\n" + "=" * 62)
print(f"RESULT:  {len(passed)} passed, {len(failed)} failed")
if failed:
    print("\nFailures:")
    for f in failed:
        print("  -", f)
print("=" * 62 + "\n")
sys.exit(1 if failed else 0)
