# Cadence

*(working name — change `APP_NAME` at the top of `app.py` when you decide)*

A proactive personal assistant. The core loop:

> **Task → Exact Time → Alarm → Your Response**

---

## The files

```
assistant-app/
├── app.py             ← the web app: which URL does what
├── auth.py            ← optional accounts (OFF by default)
├── manage_users.py    ← create/remove accounts from the terminal
├── config.py          ← settings; dev vs production
├── serve.py           ← the production server (waitress)
├── deploy.sh          ← checks, backs up, then starts it
├── requirements.txt   ← the two packages Cadence needs
├── storage.py         ← the database. The ONLY file that touches it.
├── planner.py         ← goals into curricula and schedules
├── language.py        ← sentences into tasks
├── templates/
│   ├── index.html     ← the whole interface
│   ├── login.html     ← sign in (only used if accounts are on)
│   ├── signup.html    ← create an account
│   └── error.html     ← the 404 / 500 page
├── cadence.db         ← your data (created automatically)
├── backups/           ← automatic backup before each deploy
├── logs/              ← what the server did (production only)
├── test_check.py      ← 48 checks: basics, safety, database
├── test_alarm.py      ← 34 checks: alarm, snooze, responses
├── test_features.py   ← 86 checks: days, routines, goals, language
└── test_accounts.py   ← 53 checks: accounts and data isolation
```

Each file does one job. That's why swapping JSON for SQLite touched
one module and nothing else.

---

## Running it

**One-time setup:**

```bash
cd assistant-app
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Every time:**

```bash
source venv/bin/activate
python3 app.py
```

Open **http://127.0.0.1:5000**. Stop with `Ctrl + C`.

---

## What it does

### Schedule tab
The full 24-hour day. A red line marks now. Use **‹ ›** to reach
yesterday and tomorrow.

| Action | How |
|---|---|
| Add a task | **+ Add Task** → describe it → set the time → Save |
| Speak a task | 🎤 → "call Sarah at 7 PM" → check → Save |
| Mark done | the **✓** |
| Edit | the **✎** |
| Delete | the **✕** |

When a task's time arrives you get a notification, a chime, and a card
with **Done · Not done yet · Snooze 10 mins**.

### Routines tab
Activities that repeat — Exercise, 7:00 AM, Mon–Fri. Edit the routine
and every future day changes. Pause it and it stops without losing
your history.

### Goals tab
Give it *"I want to become a web developer in one month"* and it builds
a week-by-week curriculum, then **proposes** a schedule. You pick the
time and the days, preview the whole thing, and nothing is saved until
you accept. Each session stays linked to its goal, so reminders can say
*"this is part of your goal to become a web developer."*

---

## Checking everything works

```bash
python3 test_check.py      # 48 passed
python3 test_alarm.py      # 34 passed
python3 test_features.py   # 86 passed
python3 test_accounts.py   # 53 passed  (needs no server)
```

**221 tests.** Each one snapshots your data first and restores it
afterwards, even if a test crashes.

To test the production server instead of the dev one:

```bash
CADENCE_URL=http://127.0.0.1:8000 python3 test_check.py
```

---

## User accounts

For a public deployment, run with accounts enabled and public signup enabled only if you actually want open registration:

```bash
export CADENCE_ACCOUNTS=on
export CADENCE_SIGNUP=on
```

Each account gets its own database file. Passwords are stored only as secure hashes. Login and signup attempts are rate-limited.

For a private deployment, leave `CADENCE_SIGNUP` off and create accounts with `manage_users.py`.

## Production deployment

Cadence is a single-user tool unless you say otherwise:

```bash
python3 app.py                          # no accounts — the default
CADENCE_ACCOUNTS=on python3 app.py      # ask who you are
```

Each account gets its **own database file**, so one person's
schedule cannot leak into another's. Public signup is closed by
default; you create accounts yourself:

```bash
python3 manage_users.py import-solo ade   # bring your current data in
python3 manage_users.py add sarah
python3 manage_users.py list
```

Full explanation in `docs/accounts.md`.

---

Set a strong secret before exposing the app publicly:

```bash
export CADENCE_ENV=production
export CADENCE_SECRET_KEY="replace-this-with-a-long-random-secret"
export CADENCE_ACCOUNTS=on
export CADENCE_SIGNUP=on
./deploy.sh
```

Put HTTPS in front of Waitress using your hosting provider or reverse proxy. Do not expose a production Cadence instance over plain HTTP.

### Vercel

The included `vercel.json` is ready for Vercel's Python runtime, but a
serverless function cannot safely keep a SQLite database. Before deploying,
connect a PostgreSQL database (such as Neon) and set these Vercel Production
environment variables:

```text
CADENCE_ENV=production
CADENCE_SECRET_KEY=<a unique random value, at least 32 characters>
DATABASE_URL=<your PostgreSQL connection string>
CADENCE_ACCOUNTS=on
CADENCE_SIGNUP=on
```

Cadence now refuses to boot on Vercel without `DATABASE_URL`, preventing an
unsafe deployment where account schedules could disappear between requests.
Use `CADENCE_SIGNUP=off` if you are not intentionally offering public
registration.

`deploy.sh` checks dependencies, database integrity, backups, tests when available, and production settings before starting. The source repository should not contain `cadence.db`, `accounts.db`, `users/`, backups, logs, or `.secret_key`; those are runtime/private data.

## Two limits worth knowing

**1. Alarms need the browser open.** The tab can be in the background,
but if you quit the browser entirely, nothing fires. Alarms that survive
a closed browser need push infrastructure — and iPhones restrict it
heavily.

**2. Voice needs Chrome, Edge, or Safari.** Firefox has no speech
recognition. The typing box does exactly the same job, so nothing is
lost — the microphone is a shortcut, not a separate feature.

---

## If something goes wrong

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'flask'` | Activate the venv, then `pip install flask`. |
| `Address already in use` | It's already running elsewhere. Close it, or change `port=5000` at the bottom of `app.py`. |
| Wrong times shown | Change `TIMEZONE` near the top of `app.py`. |
| Want a backup | `python3 -c "import storage; storage.backup('backup.db')"` — safe while running. |
| Worried about the data | `python3 -c "import storage; print(storage.integrity_check())"` — should print `ok`. |
| Clean slate | Delete `cadence.db`. It rebuilds empty. |
| Database files look big | `python3 -c "import storage; storage.compact()"` — folds the write-ahead log back in. It also does this automatically. |
| Something else | Read the **last line** of the terminal error — it names the file and line number. |

---

## Product rules the code enforces

1. **Exact times are never altered.** `7:30` is stored as `hour=7,
   minute=30`. The database itself rejects anything invalid.
2. **The app never invents a time.** No time → nothing is saved. The
   language parser refuses rather than guessing.
3. **The full 24-hour day always exists.**
4. **Snoozing one task never moves another.** Snooze changes only that
   task's reminder; the planned time stays put.
5. **Routines and daily tasks are separate.** A daily task never becomes
   recurring.
6. **Goal schedules are proposed, not imposed.** You set the time.
7. **Supportive, not punitive.** A missed task goes amber "still open",
   never red "FAILED". Alarms stop nagging after an hour.

---

## Not built

- **AI conversation.** The goal planner and language parser currently work with plain Python.
- **Push notifications.** Alarms require the browser to remain open.
