"""
One-off script: move tasks from tasks.json into the SQLite database.

Run it once:    python3 migrate_to_db.py

It is safe to run twice — it will tell you the database already
has tasks and stop rather than duplicating anything.

Your tasks.json is never deleted. It is renamed to
tasks.json.migrated so you keep a copy of the old data.
"""

import json
import sys
from pathlib import Path

import storage

JSON_FILE = Path(__file__).parent / "tasks.json"


def normalise(task):
    """
    Bring an old task up to the current shape.

    The very first version of Cadence stored `done: true/false`.
    Later it became `status`. Handle both.
    """
    if "status" not in task:
        task["status"] = "done" if task.get("done") else "upcoming"
    task.pop("done", None)
    task.setdefault("remind_at", None)
    task.setdefault("snooze_count", 0)
    return task


def main():
    print("\nMoving your tasks into the database")
    print("=" * 52)

    storage.init_db()

    existing = storage.stats()["total"]
    if existing:
        print(f"\nThe database already holds {existing} tasks.")
        print("Nothing to do — stopping so nothing gets duplicated.")
        print("(If you really want to start over, delete cadence.db "
              "and run this again.)\n")
        return 0

    if not JSON_FILE.exists():
        print("\nNo tasks.json found — starting with an empty database.")
        print("That's fine if this is a fresh install.\n")
        return 0

    try:
        raw = json.loads(JSON_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"\nCouldn't read tasks.json: {e}")
        print("Nothing was changed. Your file is untouched.\n")
        return 1

    print(f"\nFound {len(raw)} tasks in tasks.json")

    moved, skipped = 0, []
    for task in raw:
        try:
            t = normalise(dict(task))
            # Insert directly, preserving the original id so nothing
            # that referenced this task breaks.
            conn = storage.get_connection()
            with conn:
                conn.execute(
                    """INSERT INTO tasks (id, title, date, hour, minute,
                                          status, remind_at, snooze_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (t["id"], t["title"], t["date"], t["hour"], t["minute"],
                     t["status"], t["remind_at"], t["snooze_count"]),
                )
            moved += 1
        except Exception as e:
            skipped.append((task.get("title", "?"), str(e)))

    print(f"Moved {moved} tasks into the database")

    if skipped:
        print(f"\n{len(skipped)} could not be moved:")
        for title, why in skipped:
            print(f"   - {title}: {why}")

    # Verify before touching the original file.
    in_db = storage.stats()["total"]
    print(f"\nChecking: {in_db} tasks now in the database")

    if in_db != moved:
        print("Count mismatch — leaving tasks.json exactly where it is.")
        return 1

    if storage.integrity_check() != "ok":
        print("Database self-check failed — leaving tasks.json in place.")
        return 1

    print("Database self-check: ok")

    kept = JSON_FILE.with_suffix(".json.migrated")
    JSON_FILE.rename(kept)
    print(f"\nYour old file is kept as: {kept.name}")
    print("Delete it whenever you're comfortable.")

    print("\nDone. Cadence now uses cadence.db\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
