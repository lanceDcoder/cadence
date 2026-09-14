"""
=============================================================
  Cadence  —  a proactive personal assistant
=============================================================

The core loop:

    TASK  ->  EXACT TIME  ->  ALARM  ->  USER RESPONSE

Built on top of that:
    - recurring routines   (definitions that generate occurrences)
    - long-term goals      (curriculum -> proposed schedule)
    - natural language     ("call Sarah at 7pm")
    - voice input          (the same thing, spoken)

This file handles the WEB side: which URL does what.
    storage.py   -> the database
    planner.py   -> goals into curricula and schedules
    language.py  -> sentences into tasks
"""

from datetime import datetime, timedelta
from functools import wraps
import secrets
import hmac
from zoneinfo import ZoneInfo

from flask import (Flask, g, jsonify, redirect, render_template, request,
                   session, url_for)

import auth
import ai_assistant
import config
import language
import planner
import storage

# -------------------------------------------------------------
# 1. CONFIGURATION
# -------------------------------------------------------------
# Settings live in config.py. One environment variable decides
# whether we run in safe production mode or chatty dev mode.
app = Flask(__name__)
app.config.from_object(config.get_config())
config.validate_production_config()

APP_NAME = app.config["APP_NAME"]
TIMEZONE = ZoneInfo(app.config["TIMEZONE"])
SNOOZE_MINUTES = app.config["SNOOZE_MINUTES"]

# How late an alarm may still ring. A reminder seven hours late
# is not a reminder, it is nagging — and your principle says the
# assistant is supportive, not punitive. After this window the
# task quietly becomes "still open" instead.
ALARM_GRACE_MINUTES = app.config["ALARM_GRACE_MINUTES"]


# -------------------------------------------------------------
# 1b. ACCOUNTS  (off unless CADENCE_ACCOUNTS=on)
# -------------------------------------------------------------
# With accounts off, nothing below does anything and Cadence
# behaves exactly as it always has: one schedule, no login.
#
# With accounts on, every request picks the signed-in person's
# own database file before any route runs. Isolation comes from
# using separate files, not from remembering to filter queries.

ACCOUNTS_ON = auth.is_enabled()

# Pages reachable without logging in. Everything else redirects.
PUBLIC_ENDPOINTS = {"login", "signup", "static"}
CSRF_EXEMPT = {"static"}

if ACCOUNTS_ON:
    auth.init_accounts()


def csrf_token():
    """Return a per-session CSRF token, creating it when necessary."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token

def validate_csrf():
    """Reject state-changing requests without the session's CSRF token."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return None
    if request.endpoint in CSRF_EXEMPT:
        return None
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    expected = session.get("csrf_token")
    if not expected or not supplied or not hmac.compare_digest(str(supplied), str(expected)):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "invalid csrf token"}), 403
        return render_template("error.html", code=403,
                               message="Your session expired. Refresh the page and try again.",
                               app_name=APP_NAME), 403
    return None

def current_user():
    """The signed-in person, or None."""
    return getattr(g, "user", None)


@app.before_request
def route_to_the_right_database():
    """
    Decide whose schedule this request is allowed to touch.

    Order matters. We resolve the user FIRST and point storage at
    their file BEFORE any route function runs, so a route can
    never accidentally read the wrong database.
    """
    g.user = None

    if not ACCOUNTS_ON:
        storage.use_database(storage.DB_FILE)   # solo mode, as before
        return None

    user_id = session.get("user_id")
    if user_id:
        user = auth.get_user(user_id)
        if user:
            g.user = user
            storage.use_database(auth.db_path_for(user))
        else:
            # Account was deleted while they were signed in.
            session.clear()

    if g.user is None:
        # Not signed in. Point at a throwaway path so that even a
        # bug in the check below cannot read real data.
        if storage.using_postgres():
            storage.use_database("cadence_nobody")
        else:
            storage.use_database(auth.USER_DATA_DIR / "_nobody.db")

        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "not signed in"}), 401
        return redirect(url_for("login", next=request.path))

    return None


@app.before_request
def enforce_csrf():
    return validate_csrf()


@app.context_processor
def expose_user_to_templates():
    """Let every page know who is signed in, if anyone."""
    return {"current_user": current_user(), "accounts_on": ACCOUNTS_ON, "csrf_token": csrf_token}

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

storage.init_db()


# -------------------------------------------------------------
# 1b. SECURITY HEADERS
# -------------------------------------------------------------
# Small instructions to the browser, added to every response.
# Each one closes a specific attack:
#
#   X-Content-Type-Options  stop the browser "guessing" that an
#                           uploaded file is really a script
#   X-Frame-Options         stop other sites hiding Cadence in an
#                           invisible frame and tricking you into
#                           clicking things (clickjacking)
#   Referrer-Policy         don't leak your URLs to other sites
#   Content-Security-Policy only run scripts from this page; even
#                           if someone injected a <script> tag it
#                           would not execute

@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "microphone=(self), geolocation=(), camera=()"
    if config.is_production() and request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    # Don't advertise the exact server version to attackers.
    response.headers["Server"] = "Cadence"
    if request.endpoint in {"login", "signup"} and request.method == "GET":
        response.headers["Cache-Control"] = "no-store"
    return response


# -------------------------------------------------------------
# 1c. ERROR PAGES
# -------------------------------------------------------------
# In production a crash must NEVER show a traceback. It gets
# logged for you and the visitor sees a plain apology.

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "not found"}), 404
    return render_template("error.html", code=404,
                           message="That page doesn't exist.",
                           app_name=APP_NAME), 404


@app.errorhandler(500)
@app.errorhandler(Exception)
def server_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e

    app.logger.exception("Unhandled error on %s", request.path)

    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "something went wrong"}), 500
    return render_template("error.html", code=500,
                           message="Something went wrong on our side.",
                           app_name=APP_NAME), 500


# -------------------------------------------------------------
# 2. TIME HELPERS
# -------------------------------------------------------------
# THE EXACT TIME RULE lives here. Hour and minute are stored as
# separate whole numbers, exactly as given. Nothing rounds them.

def now():
    return datetime.now(TIMEZONE)


def today_str():
    return now().strftime("%Y-%m-%d")


def minutes_now():
    n = now()
    return n.hour * 60 + n.minute


def format_time(hour, minute):
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12}:{minute:02d} {suffix}"


def parse_time_field(value):
    """The browser sends '14:30'. Turn it into (14, 30), or None."""
    try:
        h, m = value.split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    return (h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None


def safe_int(value, default, low, high):
    """
    Turn anything into a sensible whole number.

    Web input is untrusted: it can be text, null, a list, or missing.
    int("abc") raises and returns a 500 page, so we never call int()
    on user input without this wrapper.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(n, high))


def valid_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except (ValueError, TypeError):
        return None


def reminder_minutes(task):
    """When should this ring? The snooze time, else the planned time."""
    if task.get("remind_at"):
        h, m = task["remind_at"].split(":")
        return int(h) * 60 + int(m)
    return task["hour"] * 60 + task["minute"]


# -------------------------------------------------------------
# 3. WHICH TASK SHOULD BE RINGING?
# -------------------------------------------------------------
def find_due_task(tasks, date):
    """
    The one task that should ring right now, or None.

    Only today's tasks ring — you cannot be reminded about
    yesterday. And only within the grace window, so an alarm
    you missed this morning doesn't ambush you at 6pm.
    """
    if date != today_str():
        return None

    mins = minutes_now()
    due = [
        t for t in tasks
        if t["status"] == "upcoming"
        and reminder_minutes(t) <= mins
        and mins - reminder_minutes(t) <= ALARM_GRACE_MINUTES
    ]
    due.sort(key=reminder_minutes)
    return due[0] if due else None


# -------------------------------------------------------------
# 4. BUILDING THE VIEW
# -------------------------------------------------------------
def decorate(task):
    """Display-only extras. Storage stays clean."""
    task["time_label"] = format_time(task["hour"], task["minute"])
    if task.get("remind_at"):
        h, m = task["remind_at"].split(":")
        task["snooze_label"] = format_time(int(h), int(m))
    else:
        task["snooze_label"] = None

    # A goal session carries its goal, so the reminder can say
    # "this is part of your goal to become a web developer".
    if task.get("goal_id"):
        goal = storage.get_goal(task["goal_id"])
        task["goal_title"] = goal["title"] if goal else None
    else:
        task["goal_title"] = None
    return task


def build_day(tasks):
    """All 24 hours, each holding its tasks at their PLANNED time."""
    hours = []
    for hour in range(24):
        in_hour = sorted([t for t in tasks if t["hour"] == hour],
                         key=lambda t: t["minute"])
        hours.append({"hour": hour,
                      "label": format_time(hour, 0),
                      "tasks": in_hour})
    return hours


def build_assistant_message(tasks, date):
    """
    The assistant panel.

    The SCHEDULE answers "when is something supposed to happen?"
    The ASSISTANT answers "what should I know right now?"
    """
    current = now()
    is_today = (date == today_str())

    if current.hour < 12:
        greeting = "Good morning!"
    elif current.hour < 17:
        greeting = "Good afternoon!"
    else:
        greeting = "Good evening!"

    if not is_today:
        target = datetime.strptime(date, "%Y-%m-%d").date()
        delta = (target - current.date()).days
        if delta == 1:
            greeting = "Tomorrow"
        elif delta == -1:
            greeting = "Yesterday"
        else:
            greeting = target.strftime("%A, %d %B")

    count = len(tasks)
    done = [t for t in tasks if t["status"] == "done"]
    still_open = [t for t in tasks if t["status"] == "open"]

    if count == 0:
        summary = ("Nothing scheduled today yet." if is_today
                   else "Nothing scheduled for this day.")
    else:
        thing = "thing" if count == 1 else "things"
        when = "today" if is_today else "this day"
        summary = f"You have {count} {thing} scheduled {when}."

    if not is_today:
        if count and len(done) == count:
            next_up = "Everything here is done."
        elif count:
            next_up = f"{len(done)} of {count} complete."
        else:
            next_up = "Add something with the button below."
        return {"greeting": greeting, "summary": summary, "next_up": next_up}

    upcoming = sorted(
        [t for t in tasks if t["status"] == "upcoming"
         and reminder_minutes(t) >= minutes_now()],
        key=reminder_minutes)

    # Supportive, never punitive.
    if upcoming:
        nxt = upcoming[0]
        next_up = f"Next up: {nxt['time_label']} — {nxt['title']}"
    elif still_open:
        n = len(still_open)
        thing = "thing" if n == 1 else "things"
        next_up = (f"{n} {thing} still open. "
                   "Give them a new time whenever you're ready.")
    elif count and len(done) == count:
        next_up = "Everything on today's schedule is done. Nice work."
    elif count:
        next_up = "Nothing further scheduled today."
    else:
        next_up = "Add your first task to get started."

    return {"greeting": greeting, "summary": summary, "next_up": next_up}


def expire_stale_alarms(tasks):
    """
    Quietly retire alarms that are long past.

    Rather than ringing at 6pm about a 6:30am task, we mark it
    "still open" — visible, unjudged, and you can give it a new
    time. Only for today; other days are history.
    """
    mins = minutes_now()
    for task in tasks:
        if (task["status"] == "upcoming"
                and mins - reminder_minutes(task) > ALARM_GRACE_MINUTES):
            storage.update_task(task["id"], status="open", remind_at=None)
            task["status"] = "open"
            task["remind_at"] = None
    return tasks


# -------------------------------------------------------------
# 5. THE HOME SCREEN
# -------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    """Sign in. Only reachable when accounts are switched on."""
    if not ACCOUNTS_ON:
        return redirect(url_for("home"))
    if current_user():
        return redirect(url_for("home"))

    error = None
    username = ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()[:60]
        password = request.form.get("password") or ""
        rate_key = "login:" + username.lower()
        if auth.rate_limit(rate_key, limit=10, window_seconds=900):
            error = "Too many sign-in attempts. Try again in 15 minutes."
            user = None
        else:
            user, error = auth.verify(username, password)
        if user:
            auth.clear_rate_limit(rate_key)
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = True
            # Only follow "next" if it is a path on this site.
            # An absolute URL here would be an open redirect.
            nxt = request.args.get("next") or ""
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("home"))

    return render_template("login.html", error=error, username=username,
                           app_name=APP_NAME,
                           allow_signup=auth.allow_signup(),
                           no_accounts_yet=auth.count_users() == 0)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """
    Create an account.

    Two ways in: the owner opened signup with CADENCE_SIGNUP=on,
    or there are no accounts yet and somebody has to make the
    first one.
    """
    if not ACCOUNTS_ON:
        return redirect(url_for("home"))

    first_run = auth.count_users() == 0
    if not auth.allow_signup() and not first_run:
        return redirect(url_for("login"))

    error = None
    username = display = ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()[:60]
        display = (request.form.get("display_name") or "").strip()[:60]
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

        signup_key = "signup:" + (request.remote_addr or "unknown")
        if auth.rate_limit(signup_key, limit=5, window_seconds=3600):
            error = "Too many account creation attempts. Try again later."
            user = None
        elif password != confirm:
            error = "Those two passwords don't match."
            user = None
        else:
            # The very first account is the owner.
            user, error = auth.create_user(username, password,
                                           display or username,
                                           is_admin=first_run)
            if user:
                auth.clear_rate_limit(signup_key)
                session.clear()
                session["user_id"] = user["id"]
                session["csrf_token"] = secrets.token_urlsafe(32)
                session.permanent = True
                return redirect(url_for("home"))

    return render_template("signup.html", error=error, username=username,
                           display_name=display, app_name=APP_NAME,
                           first_run=first_run)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    if ACCOUNTS_ON:
        return redirect(url_for("login"))
    return redirect(url_for("home"))


@app.route("/")
def home():
    date = valid_date(request.args.get("date", "")) or today_str()

    # Make sure routine occurrences exist for whichever day we show.
    # Generating on demand means changing a routine takes effect
    # immediately, with no thousands of pre-created future rows.
    storage.materialise_routines(date)

    tasks = storage.tasks_for_date(date)
    if date == today_str():
        tasks = expire_stale_alarms(tasks)
    tasks = [decorate(t) for t in tasks]

    current = now()
    day = datetime.strptime(date, "%Y-%m-%d").date()
    delta = (day - current.date()).days

    if delta == 0:
        day_label = "Today"
    elif delta == 1:
        day_label = "Tomorrow"
    elif delta == -1:
        day_label = "Yesterday"
    else:
        day_label = day.strftime("%a %d %b")

    return render_template(
        "index.html",
        app_name=APP_NAME,
        assistant=build_assistant_message(tasks, date),
        hours=build_day(tasks),
        date=date,
        day_label=day_label,
        is_today=(delta == 0),
        prev_date=(day - timedelta(days=1)).isoformat(),
        next_date=(day + timedelta(days=1)).isoformat(),
        today_label=day.strftime("%A, %d %B %Y"),
        current_hour=current.hour,
        current_minute=current.minute,
        snooze_minutes=SNOOZE_MINUTES,
        routines=storage.all_routines(),
        goals=[{**g, "progress": storage.goal_progress(g["id"])}
               for g in storage.all_goals()],
        day_names=DAY_NAMES,
    )


# -------------------------------------------------------------
# 6. THE ALARM
# -------------------------------------------------------------
@app.route("/api/due")
def api_due():
    """
    The browser asks this every few seconds: "is anything ringing?"

    Python cannot reach into an already-open page, so the page
    has to keep asking.
    """
    date = today_str()
    storage.materialise_routines(date)
    tasks = expire_stale_alarms(storage.tasks_for_date(date))
    task = find_due_task(tasks, date)
    if not task:
        return jsonify({"task": None})

    goal_title = None
    if task["goal_id"]:
        goal = storage.get_goal(task["goal_id"])
        goal_title = goal["title"] if goal else None

    return jsonify({"task": {
        "id": task["id"],
        "title": task["title"],
        "time_label": format_time(task["hour"], task["minute"]),
        "snooze_count": task["snooze_count"],
        "goal_title": goal_title,
        "session_note": task["session_note"],
    }})


@app.route("/tasks/<task_id>/respond", methods=["POST"])
def respond(task_id):
    """
    Done / Not done yet / Snooze.

    Snooze moves ONLY this task's reminder. Nothing cascades.
    """
    action = (request.get_json(silent=True) or {}).get("action")
    task = storage.get_task(task_id)
    if not task:
        return jsonify({"ok": False, "error": "task not found"}), 404

    if action == "done":
        storage.update_task(task_id, status="done", remind_at=None)
        status = "done"
    elif action == "open":
        # "Not done yet" — stays visible, no scolding.
        storage.update_task(task_id, status="open", remind_at=None)
        status = "open"
    elif action == "snooze":
        # Ring again in 10 minutes. The PLANNED time is left alone,
        # so the timeline still shows what you intended.
        later = min(minutes_now() + SNOOZE_MINUTES, 23 * 60 + 59)
        storage.update_task(task_id,
                            remind_at=f"{later // 60:02d}:{later % 60:02d}",
                            snooze_count=task["snooze_count"] + 1)
        status = task["status"]
    else:
        return jsonify({"ok": False, "error": "unknown action"}), 400

    return jsonify({"ok": True, "status": status})


# -------------------------------------------------------------
# 7. TASKS
# -------------------------------------------------------------
@app.route("/tasks", methods=["POST"])
def create_task():
    title = request.form.get("title", "").strip()
    parsed = parse_time_field(request.form.get("time", ""))
    date = valid_date(request.form.get("date", "")) or today_str()

    # A task needs a time before it is scheduled, and the app never
    # invents one. Missing either piece? Nothing is saved.
    if not title or parsed is None:
        return redirect(url_for("home", date=date))

    hour, minute = parsed
    storage.add_task(title, hour, minute, date)
    return redirect(url_for("home", date=date))


@app.route("/tasks/<task_id>/edit", methods=["POST"])
def edit_task(task_id):
    title = request.form.get("title", "").strip()
    parsed = parse_time_field(request.form.get("time", ""))
    task = storage.get_task(task_id)
    date = task["date"] if task else today_str()

    if not title or parsed is None or not task:
        return redirect(url_for("home", date=date))

    hour, minute = parsed
    # A new time is a fresh start: clear the snooze, and let a task
    # you'd marked "not done yet" ring again.
    status = "upcoming" if task["status"] == "open" else task["status"]
    storage.update_task(task_id, title=title, hour=hour, minute=minute,
                        status=status, remind_at=None, snooze_count=0)
    return redirect(url_for("home", date=date))


@app.route("/tasks/<task_id>/toggle", methods=["POST"])
def toggle_task(task_id):
    task = storage.get_task(task_id)
    if task:
        if task["status"] == "done":
            storage.update_task(task_id, status="upcoming")
        else:
            storage.update_task(task_id, status="done", remind_at=None)
    return redirect(url_for("home", date=task["date"] if task else None))


@app.route("/tasks/<task_id>/delete", methods=["POST"])
def delete_task(task_id):
    task = storage.get_task(task_id)
    date = task["date"] if task else today_str()
    storage.delete_task(task_id)
    return redirect(url_for("home", date=date))


# -------------------------------------------------------------
# 8. NATURAL LANGUAGE  (typed or spoken — same code)
# -------------------------------------------------------------
@app.route("/api/parse", methods=["POST"])
def api_parse():
    """
    Understand a sentence, but DON'T save anything yet.

    The user sees what we understood and confirms. That matters:
    if we misheard "at 7" as 7 PM when you meant 7 AM, you catch
    it before it becomes a wrong alarm.
    """
    raw = (request.get_json(silent=True) or {}).get("text", "")
    text = raw if isinstance(raw, str) else str(raw or "")
    results = language.parse_many(text[:2000])

    out = []
    for r in results:
        item = {
            "ok": r["ok"], "reason": r["reason"], "title": r["title"],
            "ambiguous": r["ambiguous"],
        }
        if r["ok"]:
            offset = r["day_offset"] or 0
            date = (now().date() + timedelta(days=offset)).isoformat()
            item.update({
                "hour": r["hour"], "minute": r["minute"], "date": date,
                "time_label": format_time(r["hour"], r["minute"]),
                "time_value": f"{r['hour']:02d}:{r['minute']:02d}",
                "day_label": {0: "today", 1: "tomorrow"}.get(offset, date),
            })
        out.append(item)

    return jsonify({"results": out})


@app.route("/api/confirm", methods=["POST"])
def api_confirm():
    """Save the tasks the user just approved."""
    payload = request.get_json(silent=True) or {}
    items = payload.get("tasks")
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "expected a list of tasks"}), 400

    created = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:500]
        parsed = parse_time_field(item.get("time", ""))
        date = valid_date(item.get("date", "")) or today_str()
        if title and parsed:
            storage.add_task(title, parsed[0], parsed[1], date)
            created += 1
    return jsonify({"ok": True, "created": created})


# -------------------------------------------------------------
# 9. RECURRING ROUTINES
# -------------------------------------------------------------
# A routine is a DEFINITION. It generates occurrences.
# Editing the routine changes future days; editing one occurrence
# changes only that day. That distinction is the whole point.

@app.route("/routines", methods=["POST"])
def create_routine():
    title = request.form.get("title", "").strip()
    parsed = parse_time_field(request.form.get("time", ""))
    days = [int(d) for d in request.form.getlist("days") if d.isdigit()]

    if not title or parsed is None or not days:
        return redirect(url_for("home"))

    storage.add_routine(title, parsed[0], parsed[1], days, today_str())
    return redirect(url_for("home"))


@app.route("/routines/<routine_id>/edit", methods=["POST"])
def edit_routine(routine_id):
    """
    Change the routine itself — "move my exercise routine to 6 PM".

    Future occurrences are regenerated at the new time. Past ones
    stay as they were: history records what happened, not what
    you later decided.
    """
    title = request.form.get("title", "").strip()
    parsed = parse_time_field(request.form.get("time", ""))
    days = [int(d) for d in request.form.getlist("days") if d.isdigit()]

    if not title or parsed is None or not days:
        return redirect(url_for("home"))

    storage.update_routine(routine_id, title=title, hour=parsed[0],
                           minute=parsed[1], days=days)
    storage.drop_future_occurrences(routine_id, today_str())
    storage.materialise_routines(today_str())
    return redirect(url_for("home"))


@app.route("/routines/<routine_id>/pause", methods=["POST"])
def pause_routine(routine_id):
    """Stop a routine without deleting it. Your history is kept."""
    routine = storage.get_routine(routine_id)
    if routine:
        new_state = not routine["active"]
        storage.update_routine(routine_id, active=new_state)
        if not new_state:
            storage.drop_future_occurrences(routine_id, today_str())
        else:
            storage.materialise_routines(today_str())
    return redirect(url_for("home"))


@app.route("/routines/<routine_id>/delete", methods=["POST"])
def remove_routine(routine_id):
    storage.delete_routine(routine_id, keep_past=True)
    return redirect(url_for("home"))


# -------------------------------------------------------------
# 10. LONG-TERM GOALS
# -------------------------------------------------------------
@app.route("/api/goal/plan", methods=["POST"])
def api_goal_plan():
    """
    Turn a goal into a curriculum. PROPOSAL ONLY — nothing saved.

    The user reviews the plan and chooses the time before any of
    it reaches the timeline.
    """
    data = request.get_json(silent=True) or {}
    text = str(data.get("goal") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "no goal given"}), 400

    weeks = safe_int(data.get("weeks"), planner.parse_duration(text), 1, 52)

    # Goal planning uses a paid external service. Limit it per signed-in
    # account so a leaked browser session cannot exhaust the API budget.
    if ai_assistant.is_configured() and ACCOUNTS_ON:
        user = current_user()
        if user and auth.rate_limit("ai-goal:" + user["id"],
                                    limit=12, window_seconds=3600):
            return jsonify({"ok": False,
                            "error": "You've reached the planning limit. Try again in an hour."}), 429

    if ai_assistant.is_configured():
        try:
            result = ai_assistant.build_goal_plan(text, weeks)
            return jsonify({"ok": True, "subject": planner.detect_subject(text),
                            "assistant": "Gemini", **result})
        except ai_assistant.AssistantError as exc:
            # Planning remains useful during a provider outage. The interface
            # clearly tells the user that it used the local planner instead.
            notice = str(exc) + " A standard Cadence plan is shown instead."
    else:
        notice = "Add GEMINI_API_KEY to enable personalised AI planning. A standard Cadence plan is shown instead."

    return jsonify({
        "ok": True,
        "title": planner.clean_goal_title(text),
        "weeks": weeks,
        "subject": planner.detect_subject(text),
        "plan": planner.build_curriculum(text, weeks),
        "assistant": "Cadence",
        "notice": notice,
    })


@app.route("/api/goal/preview", methods=["POST"])
def api_goal_preview():
    """
    Show the proposed schedule at the user's chosen time.

    Still nothing saved. The user can change the time and preview
    again as many times as they like.
    """
    data = request.get_json(silent=True) or {}
    plan = data.get("plan") or []
    parsed = parse_time_field(data.get("time", ""))
    raw_days = data.get("days")
    days = ([int(d) for d in raw_days if str(d).isdigit() and 0 <= int(d) <= 6]
            if isinstance(raw_days, list) else [])
    start = valid_date(data.get("start")) or today_str()

    if parsed is None or not days or not isinstance(plan, list) or not plan:
        return jsonify({"ok": False, "error": "need a time and at least one day"}), 400

    sessions = planner.propose_schedule(plan, start, parsed[0], parsed[1], days)
    for s in sessions:
        s["time_label"] = format_time(s["hour"], s["minute"])
        s["day_label"] = datetime.strptime(s["date"], "%Y-%m-%d").strftime("%a %d %b")

    return jsonify({"ok": True, "sessions": sessions,
                    "count": len(sessions)})


@app.route("/api/goal/accept", methods=["POST"])
def api_goal_accept():
    """
    The user approved the schedule. NOW we save it.

    Each session keeps its goal_id, so the reminder can say
    "this is part of your goal to become a web developer".
    """
    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or "").strip()
    weeks = safe_int(data.get("weeks"), 4, 1, 52)
    plan = data.get("plan") if isinstance(data.get("plan"), list) else []
    sessions = data.get("sessions") if isinstance(data.get("sessions"), list) else []

    if not title or not sessions:
        return jsonify({"ok": False, "error": "nothing to save"}), 400

    goal_id = storage.add_goal(title[:200], weeks)
    topics = []
    for w in plan:
        if not isinstance(w, dict):
            continue
        week_no = safe_int(w.get("week"), 1, 1, 52)
        for i, topic in enumerate(w.get("topics") or []):
            if isinstance(topic, dict):
                title = str(topic.get("title") or "").strip()[:200]
                details = str(topic.get("details") or "").strip()[:1200]
            else:
                title, details = str(topic).strip()[:200], ""
            if title:
                topics.append((week_no, i, title, details))
    storage.set_topics(goal_id, topics)

    created = 0
    for s in sessions:
        if not isinstance(s, dict):
            continue
        hour = safe_int(s.get("hour"), -1, 0, 23)
        minute = safe_int(s.get("minute"), -1, 0, 59)
        parsed = (hour, minute) if hour >= 0 and minute >= 0 else None
        date = valid_date(s.get("date"))
        if parsed and date:
            storage.add_task(str(s.get("topic") or "Session")[:200],
                             parsed[0], parsed[1], date,
                             goal_id=goal_id,
                             session_note=f"Week {safe_int(s.get('week'), 1, 1, 52)}")
            created += 1

    storage.update_goal(goal_id, status="active")
    return jsonify({"ok": True, "goal_id": goal_id, "created": created})


@app.route("/goals/<goal_id>/delete", methods=["POST"])
def remove_goal(goal_id):
    storage.delete_goal(goal_id)
    return redirect(url_for("home"))


@app.route("/api/goal/<goal_id>")
def api_goal_detail(goal_id):
    goal = storage.get_goal(goal_id)
    if not goal:
        return jsonify({"ok": False}), 404
    return jsonify({
        "ok": True, "goal": goal, "today": today_str(),
        "topics": storage.get_topics(goal_id),
        "progress": storage.goal_progress(goal_id),
        "sessions": [
            {**s, "time_label": format_time(s["hour"], s["minute"])}
            for s in storage.goal_sessions(goal_id)
        ],
    })


# -------------------------------------------------------------
# 11. STARTING THE SERVER
# -------------------------------------------------------------
if __name__ == "__main__":
    # This is the DEVELOPMENT server. It is single-threaded, slow,
    # and not built to face the internet. deploy.sh uses waitress
    # instead for anything real.
    import os
    if config.is_production():
        print("CADENCE_ENV=production is set — use ./deploy.sh, not app.py")
        raise SystemExit(1)

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=app.config["DEBUG"])
