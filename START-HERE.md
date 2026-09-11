# Running Cadence in VS Code

Start to finish. Roughly five minutes.

If something goes wrong, the last section covers every error I
could think of.

---

## Step 0 — Do you have Python?

Cadence needs **Python 3.9 or newer**. It was built on 3.13.

Open VS Code, then open a terminal inside it:
**Terminal → New Terminal** (or `` Ctrl+` ``).

Type:

```bash
python3 --version
```

**Windows users:** use `python` instead of `python3` — everywhere
in this document. So `python --version`.

You want to see `Python 3.9.x` or higher.

**Nothing found?** Install from [python.org/downloads](https://www.python.org/downloads/).
On Windows, tick **"Add Python to PATH"** on the first screen —
it's easy to miss and everything fails without it.

---

## Step 1 — Open the folder

Unzip `cadence.zip` somewhere sensible (Documents is fine).

In VS Code: **File → Open Folder** → pick the `cadence` folder.

The file list on the left should show `app.py`, `storage.py`,
`templates/` and the rest. If you see a *folder* called `cadence`
inside the folder you opened, go one level deeper.

VS Code may suggest installing the **Python extension** —
accept. You don't need it to run Cadence, but it makes editing
much nicer.

---

## Step 2 — Create a virtual environment

A "virtual environment" is a private box of packages just for this
project. Without it, Cadence's packages mix with everything else
on your computer and versions start fighting. It's one command and
it saves real pain later.

```bash
python3 -m venv .venv
```

Then switch it on:

**Mac / Linux:**
```bash
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
.venv\Scripts\activate.bat
```

Your prompt should now start with `(.venv)`. That's how you know
it's active.

> **PowerShell says "running scripts is disabled"?**
> Run this once, then try again:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

---

## Step 3 — Install the two packages

```bash
pip install -r requirements.txt
```

That installs Flask (the web framework) and waitress (the
production server). Nothing else — Cadence deliberately has only
two outside dependencies.

---

## Step 4 — Run it

For everyday use while you're editing:

```bash
python3 app.py
```

You'll see something like:

```
 * Running on http://127.0.0.1:5000
```

**Ctrl+click that link**, or open <http://127.0.0.1:5000> yourself.

Your schedule should appear: 55 tasks, 4 routines, 2 goals — the
data came with the download.

**To stop it:** `Ctrl+C` in the terminal.

---

## Step 5 — Check everything survived the trip

With the app **still running**, open a *second* terminal in VS Code
(the `+` icon in the terminal panel), activate the venv again
(step 2), and run:

```bash
python3 test_check.py
python3 test_alarm.py
python3 test_features.py
```

Expect **48**, **34**, and **86** passed, **0 failed** — 168 checks
in total.

If all three pass, the download is intact and working. That's a
much stronger signal than the page merely loading.

---

## Running the production server instead

`python3 app.py` is the *development* server: single-request,
verbose errors, fine for building.

When you want the real one:

**Mac / Linux:**
```bash
./deploy.sh
```

First time only, make it runnable:
```bash
chmod +x deploy.sh
```

`deploy.sh` checks Python, checks packages, checks the database,
**backs up your data**, runs the tests, confirms debug is off, then
starts waitress on port 8000.

**Windows** — `deploy.sh` is a bash script and won't run in
PowerShell. Use this instead:

```powershell
$env:CADENCE_ENV="production"
python serve.py
```

You'll get the same server on <http://127.0.0.1:8000>, just without
the pre-flight checks. (Git Bash or WSL will run `deploy.sh`
normally if you have either.)

---

## Light and dark

Cadence follows whatever your computer or phone is set to. If your
system is in dark mode, Cadence opens dark.

To override it, press the **🌙 / ☀️ button** in the top-right of the
purple header. Your choice is remembered on that device.

To go back to "just follow my system", clear the site data for
Cadence in your browser settings.

---

## Want more than one person to use it?

Cadence is single-user by default and stays that way unless you
ask. If you want separate accounts:

```bash
# bring your current schedule into an account
python3 manage_users.py import-solo ade

# add anyone else
python3 manage_users.py add sarah

# start with accounts on
CADENCE_ACCOUNTS=on python3 app.py
```

Windows: `$env:CADENCE_ACCOUNTS="on"; python app.py`

Each account gets its own database file, so schedules cannot mix.
Strangers can't sign themselves up — you create the accounts.
Full details in `docs/accounts.md`.

---

## Two things worth knowing

**1. The alarm needs an open tab.** Cadence's alarm rings in the
browser. Leave the tab open — background is fine, closed is not.
Real phone notifications are a separate, larger job.

**2. Your data is one file.** Everything lives in `cadence.db`.
Back it up by copying that file **while the app is stopped** —
copying it while running gives you a corrupt snapshot. Safer:

```bash
python3 -c "import storage; storage.backup('my-backup.db')"
```

That works even while it's running.

---

## When it goes wrong

**`python3: command not found`** (Windows)
Use `python`. If that fails too, Python isn't on your PATH —
reinstall and tick "Add Python to PATH".

**`No module named flask`**
The venv isn't active, or step 3 didn't happen. Check for
`(.venv)` in your prompt, then re-run
`pip install -r requirements.txt`.

**`Address already in use` / port 5000 busy**
Something's already there. On Mac, it's often AirPlay Receiver
(System Settings → General → AirDrop & Handoff). Or just use a
different port:
```bash
PORT=5050 python3 app.py
```
Windows: `$env:PORT="5050"; python app.py`

**Page loads but is unstyled or blank**
The `templates/` folder didn't come across. It must sit next to
`app.py` and contain `index.html` and `error.html`.

**`no such table: tasks`**
`cadence.db` is missing or corrupt. Cadence rebuilds it empty:
```bash
python3 -c "import storage; storage.init_db()"
```
You'll get a working app with no tasks in it.

**Tests fail with connection errors**
The app must be *running* in another terminal — the tests talk to
it over HTTP. Start `python3 app.py` first.

**Tests fail against the production server**
Point them at the right port:
```bash
CADENCE_URL=http://127.0.0.1:8000 python3 test_check.py
```

**Something else**
Copy the full red error text and send it to me. The last line
matters most.

---

## What's in the folder

```
cadence/
├── app.py             the web app: which URL does what
├── storage.py         the database. The ONLY file that touches it.
├── planner.py         goals into curricula and schedules
├── language.py        sentences into tasks
├── config.py          settings; development vs production
├── serve.py           the production server
├── deploy.sh          checks, backs up, then starts it
├── requirements.txt   the two packages needed
├── cadence.db         your data
├── templates/         the interface
├── docs/              product definition, decisions, hosting
├── test_check.py      48 checks
├── test_alarm.py      34 checks
└── test_features.py   86 checks
```

`README.md` has the fuller tour. `docs/hosting-options.md` covers
putting Cadence somewhere permanent — worth reading before you
decide anything about servers.
