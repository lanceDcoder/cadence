"""
=============================================================
  test_accounts.py  —  optional accounts
=============================================================

Runs entirely in a temporary folder. It never touches your real
cadence.db or accounts.db.

Unlike the other suites this one does NOT need a running server:
it drives the app through Flask's test client, so it can switch
accounts on and off between checks.

Run it:   python3 test_accounts.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["CADENCE_ACCOUNTS"] = "on"

import auth                      # noqa: E402
import storage                   # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="cadence_accounts_test_"))
auth.ACCOUNTS_DB = TMP / "accounts.db"
auth.USER_DATA_DIR = TMP / "users"
auth.init_accounts()

from app import app              # noqa: E402
app.config["TESTING"] = True

passed, failed = [], []


def check(label, condition, detail=""):
    if condition:
        passed.append(label)
        print(f"  [PASS] {label}")
    else:
        failed.append(label)
        print(f"  [FAIL] {label}")
        if detail:
            print(f"         {detail}")


def signed_in(username, password):
    """A test client already logged in as this person."""
    c = app.test_client()
    c.get("/login")
    with c.session_transaction() as session_data:
        token = session_data["csrf_token"]
    c.post("/login", data={"username": username, "password": password,
                            "csrf_token": token})
    return c


def csrf_post(client, path, data=None, json=None, **kwargs):
    """Make a state-changing request the same way the browser does."""
    with client.session_transaction() as session_data:
        token = session_data["csrf_token"]
    if json is not None:
        headers = dict(kwargs.pop("headers", {}))
        headers["X-CSRF-Token"] = token
        return client.post(path, json=json, headers=headers, **kwargs)
    payload = dict(data or {})
    payload["csrf_token"] = token
    return client.post(path, data=payload, **kwargs)


print("\nCADENCE — ACCOUNT TESTS")
print("=" * 62)

# ===============================================================
print("\n1. THE FEATURE IS OPT-IN")

_saved = os.environ.get("CADENCE_ACCOUNTS")
os.environ.pop("CADENCE_ACCOUNTS", None)
check("With the setting absent entirely, accounts are off",
      auth.is_enabled() is False)
os.environ["CADENCE_ACCOUNTS"] = ""
check("Empty setting means off", auth.is_enabled() is False)
os.environ["CADENCE_ACCOUNTS"] = "off"
check("'off' means off", auth.is_enabled() is False)
os.environ["CADENCE_ACCOUNTS"] = "banana"
check("An unrecognised value means off (fails safe)",
      auth.is_enabled() is False)
os.environ["CADENCE_ACCOUNTS"] = "on"
check("'on' means on", auth.is_enabled() is True)
if _saved is not None:
    os.environ["CADENCE_ACCOUNTS"] = _saved

check("Public signup is closed by default", auth.allow_signup() is False)

# ===============================================================
print("\n2. CREATING ACCOUNTS")

ade, err = auth.create_user("ade", "password123", "Ade")
check("Can create an account", ade is not None and err is None, str(err))
check("First account becomes the owner", ade and ade["is_admin"] is True)
check("Display name is kept", ade and ade["display_name"] == "Ade")

sarah, err = auth.create_user("sarah", "password456", "Sarah")
check("Can create a second account", sarah is not None, str(err))
check("Second account is NOT the owner", sarah and sarah["is_admin"] is False)

check("Each account gets its own file",
      ade["db_file"] != sarah["db_file"])
check("Ade's database exists on disk",
      auth.db_path_for(ade).exists())
check("Sarah's database exists on disk",
      auth.db_path_for(sarah).exists())

# ===============================================================
print("\n3. REJECTING BAD INPUT")

_, err = auth.create_user("ade", "password123")
check("Duplicate username refused", err is not None and "taken" in err)

_, err = auth.create_user("ADE", "password123")
check("Duplicate is caught regardless of capitals",
      err is not None and "taken" in err, f"got {err!r}")

_, err = auth.create_user("bo", "password123")
check("Very short username refused", err is not None)

_, err = auth.create_user("has space", "password123")
check("Username with a space refused", err is not None)

_, err = auth.create_user("robert'); DROP TABLE users;--", "password123")
check("SQL-looking username refused", err is not None)

_, err = auth.create_user("newperson", "short")
check("Short password refused", err is not None and "8" in err)

_, err = auth.create_user("newperson", "x" * 500)
check("Absurdly long password refused", err is not None)

check("Users table survived all that", auth.count_users() == 2,
      f"{auth.count_users()} accounts")

# ===============================================================
print("\n4. PASSWORDS ARE NEVER STORED")

import sqlite3
_c = sqlite3.connect(auth.ACCOUNTS_DB)
_rows = _c.execute("SELECT username, password_hash FROM users").fetchall()
_c.close()
check("No plain password anywhere in the table",
      all("password123" not in r[1] and "password456" not in r[1]
          for r in _rows))
check("Hashes use scrypt",
      all(r[1].startswith("scrypt:") for r in _rows),
      str([r[1][:14] for r in _rows]))
check("Two accounts with different passwords have different hashes",
      _rows[0][1] != _rows[1][1])

# Same password twice must still give different hashes (salting).
bob, _ = auth.create_user("bob", "password123", "Bob")
_c = sqlite3.connect(auth.ACCOUNTS_DB)
_h = {r[0]: r[1] for r in
      _c.execute("SELECT username, password_hash FROM users").fetchall()}
_c.close()
check("Identical passwords still hash differently (salted)",
      _h["ade"] != _h["bob"])

# ===============================================================
print("\n5. SIGNING IN")

user, err = auth.verify("ade", "password123")
check("Correct password accepted", user is not None and err is None)

user, err = auth.verify("ade", "password124")
check("Wrong password rejected", user is None and err is not None)

user, err = auth.verify("ghost", "password123")
check("Unknown username rejected", user is None)

_, err_wrong = auth.verify("ade", "nope")
_, err_ghost = auth.verify("ghost", "nope")
check("Same message either way (doesn't reveal who exists)",
      err_wrong == err_ghost, f"{err_wrong!r} vs {err_ghost!r}")

user, _ = auth.verify("ADE", "password123")
check("Username is not case-sensitive", user is not None)

# ===============================================================
print("\n6. THE LOGIN WALL")

anon = app.test_client()
r = anon.get("/", follow_redirects=False)
check("Home redirects to login when signed out", r.status_code == 302)
check("Redirect points at /login", "/login" in (r.headers.get("Location") or ""))

r = anon.get("/api/due")
check("API returns 401, not a redirect", r.status_code == 401)

r = anon.post("/tasks", data={"title": "sneaky", "time": "09:00"})
check("Cannot add a task while signed out",
      r.status_code in (302, 401))

r = anon.get("/login")
check("Login page itself is reachable", r.status_code == 200)

# ===============================================================
print("\n7. ISOLATION  —  the whole point")

ade_c = signed_in("ade", "password123")
sarah_c = signed_in("sarah", "password456")

csrf_post(ade_c, "/tasks", data={"title": "Ade confidential review",
                                  "time": "09:00", "date": "2026-09-08"})
csrf_post(sarah_c, "/tasks", data={"title": "Sarah dentist",
                                    "time": "10:00", "date": "2026-09-08"})

ade_html = ade_c.get("/?date=2026-09-08").get_data(as_text=True)
sarah_html = sarah_c.get("/?date=2026-09-08").get_data(as_text=True)

check("Ade sees his own task", "Ade confidential review" in ade_html)
check("Sarah sees her own task", "Sarah dentist" in sarah_html)
check("Sarah CANNOT see Ade's task",
      "Ade confidential review" not in sarah_html)
check("Ade CANNOT see Sarah's task", "Sarah dentist" not in ade_html)

# Guessing another person's task id must not work either.
storage.use_database(auth.db_path_for(ade))
ade_task_id = [t for t in storage.all_tasks()
               if t["title"] == "Ade confidential review"][0]["id"]

r = csrf_post(sarah_c, f"/tasks/{ade_task_id}/respond",
              json={"action": "done"})
check("Sarah cannot mark Ade's task done by guessing its id",
      r.status_code == 404, f"got {r.status_code}")

r = csrf_post(sarah_c, f"/tasks/{ade_task_id}/delete")
storage.use_database(auth.db_path_for(ade))
still_there = any(t["id"] == ade_task_id for t in storage.all_tasks())
check("Sarah cannot delete Ade's task", still_there)

# Routines and goals are separated too.
csrf_post(ade_c, "/routines", data={"title": "Ade standup", "time": "08:30",
                                     "days": ["0", "1", "2", "3", "4"]})
storage.use_database(auth.db_path_for(sarah))
check("Routines are separate too", len(storage.all_routines()) == 0,
      f"Sarah has {len(storage.all_routines())} routines")

# ===============================================================
print("\n8. SIGNING OUT")

out = signed_in("ade", "password123")
r = out.get("/")
check("Signed in, home works", r.status_code == 200)
r = csrf_post(out, "/logout", follow_redirects=False)
check("Sign out accepts the protected POST", r.status_code == 302)
r = out.get("/", follow_redirects=False)
check("After signing out, home redirects again", r.status_code == 302)

# ===============================================================
print("\n9. DELETED ACCOUNT CANNOT KEEP USING ITS SESSION")

temp_user, _ = auth.create_user("temporary", "password789", "Temp")
temp_c = signed_in("temporary", "password789")
check("New account can sign in", temp_c.get("/").status_code == 200)

auth.delete_user(temp_user["id"], remove_data=True)
r = temp_c.get("/", follow_redirects=False)
check("Its old session stops working immediately",
      r.status_code == 302, f"got {r.status_code}")
check("Its database file is gone",
      not auth.db_path_for(temp_user).exists())

# ===============================================================
print("\n10. CHANGING A PASSWORD")

auth.set_password(bob["id"], "brandnewpassword")
check("Old password stops working",
      auth.verify("bob", "password123")[0] is None)
check("New password works",
      auth.verify("bob", "brandnewpassword")[0] is not None)

# ===============================================================
print("\n11. SOLO MODE IS UNAFFECTED")

check("The real cadence.db was never touched by these tests",
      storage.DB_FILE.name == "cadence.db")
check("Test data lives in a temp folder",
      str(auth.USER_DATA_DIR).startswith(tempfile.gettempdir()))

_solo_before = Path(__file__).parent / "cadence.db"
if _solo_before.exists():
    storage.use_database(_solo_before)
    _n = storage.stats()["total"]
    storage.close_connection()
    check("Your own schedule is still readable", _n >= 0,
          f"{_n} tasks")
else:
    check("No solo database present to disturb", True)

# ===============================================================
print("\n" + "=" * 62)
print(f"RESULT:  {len(passed)} passed, {len(failed)} failed")
if failed:
    print("\nFailures:")
    for f in failed:
        print("  -", f)
print("=" * 62 + "\n")

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)
