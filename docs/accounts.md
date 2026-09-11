# User accounts (optional)

Cadence is a single-user tool by default. Accounts are a switch
you can flip if you need them — nothing changes until you do.

---

## The short version

**Do nothing** and Cadence behaves exactly as it always has: open
it, your schedule is there, no login.

**Switch it on** and it asks who you are, then shows that person's
own private schedule.

```bash
# Normal — no accounts
python3 app.py

# With accounts
CADENCE_ACCOUNTS=on python3 app.py
```

Switching it off again returns you to your original schedule,
untouched.

---

## How your data stays private

This is the part worth understanding, because it's the difference
between "probably fine" and "provably fine".

**The usual approach** is one shared database where every row
carries an owner's name, and every query says *"...and only show
rows belonging to this person"*. Cadence has 38 database queries.
Forget that condition in **one** of them and somebody silently
sees another person's schedule. Nothing crashes. No warning.

**Cadence does it differently.** Each account gets its own
database file:

```
cadence.db                    <- solo mode
users/cadence_a1b2c3.db       <- Ade's schedule
users/cadence_d4e5f6.db       <- Sarah's schedule
```

Two people cannot see each other's tasks for the same reason you
cannot read a file that was never opened. Nothing depends on
anyone remembering to add a condition.

Before each request Cadence works out who is signed in and points
at their file. If nobody is signed in it points at a dead-end path
that has no data in it, then redirects to the login page — so even
a bug in the login check reads nothing real.

The trade-off: no single query can span all users. Cadence never
needs one.

---

## Turning it on

### 1. Bring your existing schedule with you

If you've already been using Cadence, don't lose that work:

```bash
python3 manage_users.py import-solo ade
```

That creates an account called `ade` and gives it a **copy** of
your current schedule. Your original `cadence.db` is left alone,
so single-user mode still works afterwards.

### 2. Start with accounts on

```bash
CADENCE_ACCOUNTS=on python3 app.py
```

Sign in with the username and password you just chose.

### 3. Add anyone else

```bash
python3 manage_users.py add sarah
```

---

## Managing accounts

```bash
python3 manage_users.py list              # who exists
python3 manage_users.py add sarah         # create
python3 manage_users.py passwd sarah      # change a password
python3 manage_users.py remove sarah      # delete (and their data)
python3 manage_users.py import-solo ade   # bring solo data in
```

Passwords are always typed at a prompt, never given as an
argument — arguments end up in your shell history and are visible
to anyone who can list running processes.

---

## Can strangers sign themselves up?

**No, by default.** Even with accounts on, the signup page is
closed. You create accounts from the command line. That's the
right default for a family or a small group: no unknown person
can register just because they found the address.

The one exception: if **no accounts exist yet**, the signup page
opens so the first one can be created. That first account becomes
the owner.

To let anyone register:

```bash
CADENCE_ACCOUNTS=on CADENCE_SIGNUP=on python3 app.py
```

Only do this if you genuinely want a public service — it brings
along everything a public service needs, like password resets and
abuse handling, which Cadence does not have.

---

## About the passwords

- Never stored. Only a **scrypt** hash is kept, which cannot
  practically be reversed.
- Each hash is salted, so two people with the same password get
  different hashes.
- A wrong password and an unknown username give the **same**
  message, and take the same time to answer. Otherwise you'd be
  telling an attacker which usernames exist.
- Minimum 8 characters.

No extra package is needed for any of this — the hashing ships
with Flask.

---

## What is not included

Being straight with you about the limits:

- **No password reset by email.** Cadence doesn't send email. If
  someone forgets their password, the owner runs
  `manage_users.py passwd <name>`.
- **No rate limiting.** Someone could try passwords rapidly. Fine
  on a home network; a real concern on the public internet.
- **No email verification**, so public signup can't confirm anyone
  is who they say.
- **No "remember me"**, no two-factor, no account recovery.

These are all reasonable to add later. They matter mainly if you
open signup to the public — which is why that's off by default.

---

## Backups

`deploy.sh` notices when accounts are switched on and backs up
every person's schedule as well as the accounts file:

```
backups/cadence_20260908_154946.db          <- solo
backups/accounts_20260908_154946/
    accounts.db                             <- who exists
    cadence_a1b2c3.db                       <- Ade's schedule
    cadence_d4e5f6.db                       <- Sarah's schedule
```

Never back these up by copying files while the app is running —
SQLite's WAL mode means a plain copy can miss recent writes.
`deploy.sh` uses proper snapshots.

---

## Switching back

Stop the app and start it without `CADENCE_ACCOUNTS=on`. You're
back to the single schedule in `cadence.db`, exactly as before.

Account data stays in `accounts.db` and `users/` in case you turn
it on again. To remove it completely, delete both.

---

## Tested

`test_accounts.py` — 53 checks, including:

- the feature is genuinely off unless explicitly switched on, and
  an unrecognised value fails safe (off)
- passwords never appear in the database in readable form
- identical passwords produce different hashes
- signed-out visitors are redirected; the API returns 401
- **one account cannot see another's tasks, routines or goals**
- **one account cannot mark done or delete another's task even
  when given its exact id**
- a deleted account's session stops working immediately
- your solo database is never touched by any of it

Run it with `python3 test_accounts.py`. It needs no server and
works entirely in a temporary folder.
