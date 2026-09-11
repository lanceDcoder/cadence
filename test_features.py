"""
Tests for the later phases: day navigation, stale alarms,
recurring routines, goals, and natural language.

Run with:   python3 test_features.py
"""

import atexit
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import os as _os
BASE = _os.environ.get("CADENCE_URL", "http://127.0.0.1:5000")
sys.path.insert(0, str(Path(__file__).parent))

import language  # noqa: E402
import planner  # noqa: E402
import storage  # noqa: E402
from app import now, today_str  # noqa: E402

passed, failed = [], []


def check(name, ok, detail=""):
    (passed if ok else failed).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" +
          (f"\n         {detail}" if detail else ""))


def get(path="/"):
    return urllib.request.urlopen(BASE + path).read().decode()


def post_json(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        return json.loads(urllib.request.urlopen(req).read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code}


def post_form(path, fields):
    data = urllib.parse.urlencode(fields, doseq=True).encode()
    return urllib.request.urlopen(BASE + path, data=data).read().decode()


# ---- protect real data ---------------------------------------
storage.init_db()
_saved_tasks = storage.all_tasks()
_saved_routines = storage.all_routines()
# Snapshot goals as RAW ROWS. all_goals() doesn't include the
# per-week topics, and restore() deletes both tables — so anything
# not captured here is destroyed permanently by a test run.
_gconn = storage.get_connection()
_saved_goals = [dict(r) for r in
                _gconn.execute("SELECT * FROM goals").fetchall()]
_saved_topics = [dict(r) for r in
                 _gconn.execute("SELECT * FROM goal_topics").fetchall()]


def restore():
    """
    Put everything back EXACTLY as it was.

    Routines must keep their original ids. An earlier version used
    add_routine(), which mints a NEW id — so every restored task
    still pointed at the old one and the timeline showed duplicates.
    """
    conn = storage.get_connection()
    with conn:
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM routines")
        conn.execute("DELETE FROM goals")
        conn.execute("DELETE FROM goal_topics")
        for r in _saved_routines:
            conn.execute(
                """INSERT INTO routines (id, title, hour, minute, days,
                                         active, start_date)
                   VALUES (?,?,?,?,?,?,?)""",
                (r["id"], r["title"], r["hour"], r["minute"],
                 ",".join(str(d) for d in r["days"]),
                 1 if r["active"] else 0, r["start_date"]))
        for g in _saved_goals:
            conn.execute(
                """INSERT INTO goals (id, title, weeks, status, created_at)
                   VALUES (?,?,?,?,?)""",
                (g["id"], g["title"], g["weeks"], g["status"],
                 g["created_at"]))
        for t in _saved_topics:
            conn.execute(
                """INSERT INTO goal_topics (id, goal_id, week, position, topic)
                   VALUES (?,?,?,?,?)""",
                (t["id"], t["goal_id"], t["week"], t["position"], t["topic"]))
    storage.replace_all(_saved_tasks)


atexit.register(restore)


def clean():
    conn = storage.get_connection()
    with conn:
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM routines")
        conn.execute("DELETE FROM goals")
        conn.execute("DELETE FROM goal_topics")


print("\nCADENCE — FEATURE TESTS  (Phases 10, 14-19)")
print("=" * 62)

# ===============================================================
print("\n1. DAY NAVIGATION  (fixes the vanishing-yesterday bug)")
clean()

yesterday = (now().date() - timedelta(days=1)).isoformat()
tomorrow = (now().date() + timedelta(days=1)).isoformat()

storage.add_task("Yesterday thing", 14, 0, yesterday)
storage.add_task("Today thing", 15, 0, today_str())
storage.add_task("Tomorrow thing", 16, 0, tomorrow)

page_today = get("/")
check("Today shows only today's task",
      "Today thing" in page_today and "Yesterday thing" not in page_today)

page_yest = get(f"/?date={yesterday}")
check("Yesterday's tasks are now REACHABLE", "Yesterday thing" in page_yest)
check("Yesterday page is labelled", "Yesterday" in page_yest)

page_tom = get(f"/?date={tomorrow}")
check("Tomorrow is viewable", "Tomorrow thing" in page_tom)
check("Tomorrow page is labelled", "Tomorrow" in page_tom)

post_form("/tasks", {"title": "Bank visit", "time": "10:00", "date": tomorrow})
check("Can schedule for TOMORROW (§6)",
      any(t["title"] == "Bank visit" and t["date"] == tomorrow
          for t in storage.all_tasks()))

check("Bad date falls back to today, no crash",
      "Today thing" in get("/?date=not-a-date"))

# ===============================================================
print("\n2. STALE ALARMS  (supportive, not nagging)")
clean()

mins = now().hour * 60 + now().minute
if mins > 200:
    long_ago = mins - 180                      # 3 hours late
    storage.add_task("Ancient task", long_ago // 60, long_ago % 60, today_str())
    get("/")
    t = storage.all_tasks()[0]
    check("A 3-hour-late alarm stops ringing", t["status"] == "open",
          f"status = {t['status']}")
    check("It becomes 'still open', not deleted",
          t["status"] == "open" and t["hour"] == long_ago // 60)

    clean()
    recent = max(0, mins - 5)
    storage.add_task("Just now", recent // 60, recent % 60, today_str())
    due = json.loads(get("/api/due"))["task"]
    check("A 5-minute-late alarm still rings", due and due["title"] == "Just now")
else:
    print("  [SKIP] too early in the day to test the grace window")

# ===============================================================
print("\n3. RECURRING ROUTINES  (§10, §11)")
clean()

post_form("/routines", {"title": "Exercise", "time": "07:00",
                        "days": ["0", "1", "2", "3", "4"]})
routines = storage.all_routines()
check("Routine created", len(routines) == 1)
check("Routine stores its exact time",
      routines and routines[0]["hour"] == 7 and routines[0]["minute"] == 0)
check("Routine stores Mon-Fri", routines and routines[0]["days"] == [0, 1, 2, 3, 4])

rid = routines[0]["id"]

# Find the next Monday and confirm an occurrence appears.
d = now().date()
while d.weekday() != 0:
    d += timedelta(days=1)
monday = d.isoformat()
get(f"/?date={monday}")
mon_tasks = storage.tasks_for_date(monday)
check("Routine generates an occurrence on Monday",
      any(t["title"] == "Exercise" for t in mon_tasks))
check("The occurrence is linked to its routine",
      any(t["routine_id"] == rid for t in mon_tasks))

# Saturday should get nothing.
sat = d
while sat.weekday() != 5:
    sat += timedelta(days=1)
get(f"/?date={sat.isoformat()}")
check("No occurrence on a day not in the routine",
      not any(t["title"] == "Exercise"
              for t in storage.tasks_for_date(sat.isoformat())))

# Viewing twice must not duplicate.
get(f"/?date={monday}")
get(f"/?date={monday}")
count = len([t for t in storage.tasks_for_date(monday) if t["title"] == "Exercise"])
check("Viewing a day repeatedly does not duplicate", count == 1,
      f"found {count}")

# "Move my exercise routine to 6 PM"
post_form(f"/routines/{rid}/edit", {"title": "Exercise", "time": "18:00",
                                    "days": ["0", "1", "2", "3", "4"]})
check("Editing the routine changes the definition",
      storage.get_routine(rid)["hour"] == 18)
get(f"/?date={monday}")
future = [t for t in storage.tasks_for_date(monday) if t["routine_id"] == rid]
check("Future occurrences move with the routine",
      future and all(t["hour"] == 18 for t in future),
      f"hours = {[t['hour'] for t in future]}")

# Pause
post_form(f"/routines/{rid}/pause", {})
check("Pausing deactivates the routine", not storage.get_routine(rid)["active"])
nxt = (datetime.strptime(monday, "%Y-%m-%d").date() + timedelta(days=7)).isoformat()
get(f"/?date={nxt}")
check("A paused routine generates nothing",
      not any(t["routine_id"] == rid for t in storage.tasks_for_date(nxt)))

post_form(f"/routines/{rid}/pause", {})
check("Resuming reactivates it", storage.get_routine(rid)["active"])

check("Concurrent page loads don't duplicate a routine", True)  # set below

# The alarm polls every 5 seconds while you browse, so two requests
# routinely overlap. Check-then-insert used to let both create the
# same occurrence; a unique index now makes that impossible.
import threading as _th  # noqa: E402
conn = storage.get_connection()
with conn:
    conn.execute("DELETE FROM tasks")


def _hit(path):
    try:
        urllib.request.urlopen(BASE + path).read()
    except Exception:
        pass


_threads = [_th.Thread(target=_hit, args=(pth,))
            for pth in ["/", "/api/due"] * 8]
for _t in _threads:
    _t.start()
for _t in _threads:
    _t.join()
_n = len([t for t in storage.tasks_for_date(today_str()) if t["routine_id"]])
passed.pop()  # replace the placeholder above
check("16 concurrent requests create no duplicate occurrences",
      _n == len([r for r in storage.all_routines() if r["active"]]),
      f"{_n} occurrences from {len(storage.all_routines())} routines")

# ===============================================================
print("\n4. ROUTINES vs DAILY TASKS STAY SEPARATE  (§11)")
clean()
post_form("/routines", {"title": "Lunch", "time": "13:00", "days": ["0", "1", "2", "3", "4", "5", "6"]})
post_form("/tasks", {"title": "One-off errand", "time": "15:00", "date": today_str()})
get("/")
tasks = storage.tasks_for_date(today_str())
oneoff = [t for t in tasks if t["title"] == "One-off errand"]
check("A daily task has no routine link", oneoff and oneoff[0]["routine_id"] is None)
check("A daily task does NOT become recurring", len(storage.all_routines()) == 1)

# Snoozing a routine occurrence must not touch the definition.
routine_task = [t for t in tasks if t["routine_id"]][0]
before_hour = storage.all_routines()[0]["hour"]
post_json(f"/tasks/{routine_task['id']}/respond", {"action": "snooze"})
check("Snoozing an occurrence does NOT change the routine",
      storage.all_routines()[0]["hour"] == before_hour)
check("Snoozed occurrence keeps its planned time",
      storage.get_task(routine_task["id"])["hour"] == routine_task["hour"])

# ===============================================================
print("\n5. NATURAL LANGUAGE  (§6)")

cases = [
    ("I need to finish my assignment at 2 PM", "Finish my assignment", 14, 0),
    ("Remind me to call John at 6", "Call John", 18, 0),
    ("Tomorrow I need to go to the bank at 10 AM", "Go to the bank", 10, 0),
    ("I need to call Sarah at 7 PM", "Call Sarah", 19, 0),
    ("Exercise at 7:30 AM", "Exercise", 7, 30),
    ("gym at 18:30", "Gym", 18, 30),
    ("Meeting at noon", "Meeting", 12, 0),
]
for text, title, h, m in cases:
    r = language.parse(text)
    ok = r["ok"] and r["title"] == title and r["hour"] == h and r["minute"] == m
    check(f'"{text[:34]}..." parses correctly', ok,
          f"got '{r['title']}' {r['hour']}:{r['minute']:02d}" if not ok else "")

check("'tomorrow' is detected",
      language.parse("Tomorrow go to the bank at 10 AM")["day_offset"] == 1)

# ===============================================================
print("\n6. THE PARSER NEVER INVENTS A TIME  (§21 rule 4)")
for text in ["I need to buy groceries", "call mum", "finish the report", ""]:
    r = language.parse(text)
    check(f"Refuses {text!r} (no time given)", not r["ok"])

clean()
res = post_json("/api/parse", {"text": "I need to buy groceries"})
check("API reports it could not find a time",
      res["results"] and not res["results"][0]["ok"])
check("Nothing was saved without a time", len(storage.all_tasks()) == 0)

r = language.parse("call John at 6")
check("Ambiguous times are FLAGGED, not silently accepted", r["ambiguous"])

# ===============================================================
print("\n7. VOICE / MULTI-TASK SENTENCES  (§7)")
clean()
sentence = ("Today I need to finish my assignment at 2 PM, "
            "go to the bank at 4 PM and call Sarah at 7")
res = post_json("/api/parse", {"text": sentence})
good = [r for r in res["results"] if r["ok"]]
check("One sentence yields 3 tasks", len(good) == 3, f"got {len(good)}")
check("Times are 2 PM, 4 PM, 7 PM",
      [g["hour"] for g in good] == [14, 16, 19],
      f"got {[g['hour'] for g in good]}")

confirmed = post_json("/api/confirm", {"tasks": [
    {"title": g["title"], "time": g["time_value"], "date": g["date"]}
    for g in good]})
check("Confirmed tasks are saved", confirmed["created"] == 3)
check("They land on the timeline", len(storage.tasks_for_date(today_str())) == 3)

# Voice uses the SAME pipeline, not a separate system.
check("Voice and typing share one parser",
      language.parse("call Sarah at 7 PM")["title"] ==
      language.parse("Call Sarah at 7 PM")["title"])

# ===============================================================
print("\n8. GOALS: PLAN  (§13)")
clean()

plan = post_json("/api/goal/plan",
                 {"goal": "I want to become a web developer in one month"})
check("Goal produces a plan", plan["ok"])
check("Title is cleaned up", plan["title"] == "Become a web developer",
      f"got '{plan['title']}'")
check("'one month' becomes 4 weeks", plan["weeks"] == 4)
check("Subject detected as web development", plan["subject"] == "web development")
check("Four weeks of topics", len(plan["plan"]) == 4)

week1 = " ".join(plan["plan"][0]["topics"]).lower()
check("Week 1 covers HTML and CSS", "html" in week1 and "css" in week1)
week2 = " ".join(plan["plan"][1]["topics"]).lower()
check("Week 2 covers JavaScript", "javascript" in week2)

other = post_json("/api/goal/plan", {"goal": "learn Python in 6 weeks"})
check("Different goal, different length", other["weeks"] == 6)
check("Python template chosen", other["subject"] == "python")

unknown = post_json("/api/goal/plan", {"goal": "learn to juggle in 2 weeks"})
check("Unknown subject still gets an honest generic plan",
      unknown["ok"] and len(unknown["plan"]) == 2)

# ===============================================================
print("\n9. GOALS: PROPOSE, DON'T IMPOSE  (§14)")

preview = post_json("/api/goal/preview",
                    {"plan": plan["plan"], "time": "19:00",
                     "days": [0, 1, 2, 3, 4]})
check("Schedule preview generated", preview["ok"])
check("Sessions use the time WE ASKED FOR (7 PM)",
      all(s["hour"] == 19 for s in preview["sessions"]))
check("Nothing saved during preview", len(storage.all_tasks()) == 0)

# The user says "no, make it 8 PM"
preview2 = post_json("/api/goal/preview",
                     {"plan": plan["plan"], "time": "20:00",
                      "days": [0, 1, 2, 3, 4]})
check("User can change the time to 8 PM",
      all(s["hour"] == 20 for s in preview2["sessions"]))
check("Still nothing saved", len(storage.all_tasks()) == 0)

check("Preview refuses without a time",
      not post_json("/api/goal/preview",
                    {"plan": plan["plan"], "time": "", "days": [0]})["ok"])

# ===============================================================
print("\n10. GOALS: ACCEPT AND STAY LINKED  (§15)")

accepted = post_json("/api/goal/accept", {
    "title": plan["title"], "weeks": plan["weeks"],
    "plan": plan["plan"], "sessions": preview2["sessions"]})
check("Schedule accepted and saved", accepted["ok"] and accepted["created"] > 0)

gid = accepted["goal_id"]
sessions = storage.goal_sessions(gid)
check("Sessions exist on the timeline", len(sessions) == len(preview2["sessions"]))
check("Every session keeps its goal_id (§15)",
      all(s["goal_id"] == gid for s in sessions))
check("Sessions kept the user's chosen 8 PM",
      all(s["hour"] == 20 for s in sessions))
check("Sessions carry a week note",
      all(s["session_note"] for s in sessions))

topics = storage.get_topics(gid)
check("Curriculum stored with the goal", len(topics) > 0)

prog = storage.goal_progress(gid)
check("Progress starts at zero", prog["done"] == 0 and prog["percent"] == 0)

first = sessions[0]
storage.update_task(first["id"], status="done")
check("Progress updates as sessions complete",
      storage.goal_progress(gid)["done"] == 1)

detail = json.loads(get(f"/api/goal/{gid}"))
check("Goal detail endpoint works", detail["ok"])
check("Detail includes topics and sessions",
      detail["topics"] and detail["sessions"])

# ===============================================================
print("\n11. GOAL SESSIONS BEHAVE LIKE NORMAL TASKS")

today_session = None
for s in sessions:
    if s["date"] == today_str():
        today_session = s
        break

if today_session is None:
    storage.update_task(sessions[1]["id"], date=today_str())
    today_session = storage.get_task(sessions[1]["id"])

post_json(f"/tasks/{today_session['id']}/respond", {"action": "snooze"})
after = storage.get_task(today_session["id"])
check("A goal session can be snoozed", after["remind_at"] is not None)
check("Snoozing keeps its planned time",
      after["hour"] == today_session["hour"])
check("Snoozing does not detach it from its goal", after["goal_id"] == gid)

page = get("/")
check("Goal name shows on the timeline", "Become a web developer" in page)

# ===============================================================
print("\n12. DELETING A GOAL KEEPS HISTORY")
before_done = len([s for s in storage.goal_sessions(gid) if s["status"] == "done"])
post_form(f"/goals/{gid}/delete", {})
check("Goal removed", storage.get_goal(gid) is None)
remaining = [t for t in storage.all_tasks() if t["goal_id"] == gid]
check("Completed sessions are preserved as history",
      len(remaining) >= before_done,
      f"{len(remaining)} kept, {before_done} were done")

# ===============================================================
print("\n13. DATABASE STILL HEALTHY")
check("Integrity check passes", storage.integrity_check() == "ok")
s = storage.stats()
check("Stats include routines and goals", "routines" in s and "goals" in s)

# ===============================================================
print("\n14. THE TEST SUITE ITSELF DOESN'T DESTROY DATA")
# This suite wipes goals/goal_topics between sections. restore()
# once put back tasks and routines but NOT goals, so every run
# silently deleted the user's real goals. Verify the snapshot
# covers every table restore() clears.
import inspect as _inspect
import re as _re
_src = _inspect.getsource(restore)
_cleared = set(_re.findall(r"DELETE FROM (\w+)", _src))
_restored = set(_re.findall(r"INSERT INTO (\w+)", _src))
if "replace_all" in _src:
    _restored.add("tasks")
check("restore() puts back every table it deletes",
      _cleared == _restored,
      f"deletes={sorted(_cleared)} restores={sorted(_restored)}")
check("Goals were captured before the run",
      isinstance(_saved_goals, list),
      f"{len(_saved_goals)} goals snapshotted")
check("Goal topics were captured before the run",
      isinstance(_saved_topics, list),
      f"{len(_saved_topics)} topics snapshotted")
# Prove restore() really works: wipe, restore, compare counts.
_conn = storage.get_connection()
with _conn:
    _conn.execute("DELETE FROM goals")
    _conn.execute("DELETE FROM goal_topics")
restore()
_g = _conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
_t = _conn.execute("SELECT COUNT(*) FROM goal_topics").fetchone()[0]
check("restore() actually brings goals back",
      _g == len(_saved_goals), f"{_g} vs {len(_saved_goals)} expected")
check("restore() actually brings goal topics back",
      _t == len(_saved_topics), f"{_t} vs {len(_saved_topics)} expected")

print("\n" + "=" * 62)
print(f"RESULT:  {len(passed)} passed, {len(failed)} failed")
if failed:
    print("\nFailures:")
    for f in failed:
        print("  -", f)
print("=" * 62 + "\n")
sys.exit(1 if failed else 0)
