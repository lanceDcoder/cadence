#!/usr/bin/env python3
"""
=============================================================
  manage_users.py  —  accounts from the command line
=============================================================

Lets you create accounts WITHOUT opening public signup, which is
the safe default: you decide who gets in.

    python3 manage_users.py list
    python3 manage_users.py add sarah
    python3 manage_users.py passwd sarah
    python3 manage_users.py remove sarah
    python3 manage_users.py import-solo ade

Passwords are typed at a prompt, never passed as an argument —
arguments show up in your shell history and in the process list.

`import-solo` is the one to use when moving from single-user
mode: it creates an account and hands it your existing
cadence.db, so nothing is lost.
"""

import getpass
import shutil
import sys
from pathlib import Path

import auth
import storage

BASE_DIR = Path(__file__).parent


def _ask_password(prompt="Password: "):
    first = getpass.getpass(prompt)
    again = getpass.getpass("Confirm: ")
    if first != again:
        print("  Those don't match.")
        return None
    problem = auth.check_password(first)
    if problem:
        print(f"  {problem}")
        return None
    return first


def cmd_list():
    auth.init_accounts()
    users = auth.list_users()
    if not users:
        print("\n  No accounts yet.")
        print("  Create one:  python3 manage_users.py add <name>\n")
        return 0

    print(f"\n  {len(users)} account(s):\n")
    print(f"  {'USERNAME':<18} {'NAME':<20} {'OWNER':<7} "
          f"{'TASKS':<7} LAST SIGN-IN")
    print("  " + "-" * 72)
    for u in users:
        path = auth.db_path_for(u)
        try:
            storage.use_database(path)
            count = storage.stats()["total"]
        except Exception:
            count = "?"
        print(f"  {u['username']:<18} {u['display_name'][:20]:<20} "
              f"{'yes' if u['is_admin'] else '-':<7} {str(count):<7} "
              f"{u['last_login'] or 'never'}")
    print()
    return 0


def cmd_add(username, admin=False):
    auth.init_accounts()
    problem = auth.check_username(username)
    if problem:
        print(f"  {problem}")
        return 1
    if auth.get_by_username(username):
        print(f"  '{username}' already exists.")
        return 1

    display = input(f"  Display name [{username}]: ").strip() or username
    password = _ask_password()
    if password is None:
        return 1

    first = auth.count_users() == 0
    user, error = auth.create_user(username, password, display,
                                   is_admin=admin or first)
    if error:
        print(f"  {error}")
        return 1

    print(f"\n  Created '{user['username']}'"
          f"{' (owner)' if user['is_admin'] else ''}.")
    print(f"  Their schedule: users/{user['db_file']}")
    print("\n  Start with accounts on:")
    print("      CADENCE_ACCOUNTS=on python3 app.py\n")
    return 0


def cmd_passwd(username):
    auth.init_accounts()
    user = auth.get_by_username(username)
    if not user:
        print(f"  No account called '{username}'.")
        return 1
    password = _ask_password(f"New password for {username}: ")
    if password is None:
        return 1
    problem = auth.set_password(user["id"], password)
    if problem:
        print(f"  {problem}")
        return 1
    print(f"  Password changed for '{username}'.")
    return 0


def cmd_remove(username):
    auth.init_accounts()
    user = auth.get_by_username(username)
    if not user:
        print(f"  No account called '{username}'.")
        return 1

    path = auth.db_path_for(user)
    try:
        storage.use_database(path)
        count = storage.stats()["total"]
    except Exception:
        count = "an unknown number of"

    print(f"\n  This deletes '{username}' AND their {count} tasks.")
    print("  It cannot be undone.")
    if input("  Type the username to confirm: ").strip() != username:
        print("  Cancelled.")
        return 1

    storage.close_connection()
    error = auth.delete_user(user["id"], remove_data=True)
    if error:
        print(f"  {error}")
        return 1
    print(f"  Removed '{username}'.")
    return 0


def cmd_import_solo(username):
    """
    Turn the existing single-user cadence.db into an account.

    This is the migration path. The original file is COPIED, not
    moved, so single-user mode still works afterwards.
    """
    solo = BASE_DIR / "cadence.db"
    if not solo.exists():
        print("  There's no cadence.db to import.")
        return 1

    auth.init_accounts()
    if auth.get_by_username(username):
        print(f"  '{username}' already exists. Pick another name.")
        return 1

    # Read the solo database through storage, so WAL contents are
    # included. Copying the file alone would miss recent writes.
    storage.use_database(solo)
    stats = storage.stats()
    print(f"\n  Importing {stats['total']} tasks, {stats['routines']} "
          f"routines, {stats['goals']} goals into a new account.")

    display = input(f"  Display name [{username}]: ").strip() or username
    password = _ask_password()
    if password is None:
        return 1

    first = auth.count_users() == 0
    user, error = auth.create_user(username, password, display,
                                   is_admin=first)
    if error:
        print(f"  {error}")
        return 1

    # storage.backup() is a proper SQLite snapshot; a file copy is
    # not safe while WAL mode is on.
    target = auth.db_path_for(user)
    storage.use_database(solo)
    storage.close_connection()
    try:
        target.unlink()             # remove the empty one just made
    except FileNotFoundError:
        pass
    storage.use_database(solo)
    storage.backup(str(target))
    storage.close_connection()

    storage.use_database(target)
    after = storage.stats()
    storage.close_connection()

    print(f"\n  Created '{username}' with your existing schedule:")
    print(f"      {after['total']} tasks, {after['routines']} routines, "
          f"{after['goals']} goals")
    print(f"      users/{user['db_file']}")
    print(f"\n  Your original cadence.db is untouched, so")
    print(f"  single-user mode still works exactly as before.\n")
    return 0


USAGE = """
  Cadence — account management

    python3 manage_users.py list
    python3 manage_users.py add <username>
    python3 manage_users.py add <username> --admin
    python3 manage_users.py passwd <username>
    python3 manage_users.py remove <username>
    python3 manage_users.py import-solo <username>

  import-solo copies your existing single-user schedule into a
  new account. Use it when switching accounts on for the first
  time.
"""


def main(argv):
    if len(argv) < 2:
        print(USAGE)
        return 1

    cmd = argv[1].lower()
    args = argv[2:]

    if cmd == "list":
        return cmd_list()
    if cmd == "add" and args:
        return cmd_add(args[0], admin="--admin" in args)
    if cmd == "passwd" and args:
        return cmd_passwd(args[0])
    if cmd == "remove" and args:
        return cmd_remove(args[0])
    if cmd in ("import-solo", "import_solo") and args:
        return cmd_import_solo(args[0])

    print(USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
