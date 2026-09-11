# Where should Cadence actually live?

Plain-language version. No decision needed until the end, and
there's no wrong answer — they suit different lives.

---

## First, what "hosting" even means

Right now Cadence runs on your computer. You start it, you open
`localhost:5000`, and it works. Close the laptop and it's gone —
along with the alarm.

"Hosting" means putting the app on a computer that never sleeps,
so it has an address anyone (or just you) can reach from any
device, any time.

That's the entire idea. Everything below is just *whose computer*.

---

## The thing that decides it: the alarm

Cadence's whole point is TASK → EXACT TIME → ALARM → RESPONSE.

There's a limitation we've known about since the alarm was built,
and it drives this choice:

> **The alarm rings in the browser. A tab must be open for it
> to ring.**

Hosting Cadence somewhere else does *not* fix that. A server in
Germany can hold your tasks perfectly and still not make your
phone buzz — because the buzzing happens in the browser tab.

So be clear about what hosting actually buys you:

| It gives you | It does not give you |
|---|---|
| Your schedule on your phone | Alarms with no tab open |
| Same data on every device | Notifications when the phone is locked |
| Nothing lost if the laptop dies | Anything the laptop version can't do |

Real phone notifications need push notifications or an app —
a separate, considerably bigger piece of work. Worth doing later.
Not part of this decision.

---

## Option 1 — Just your own computer

Keep it exactly as it is. Run `./deploy.sh` when you want it.

**Good:** free · private, data never leaves your machine · already
works · nothing new to learn.

**Bad:** only on that computer · off when it's off.

**Suits you if** you work at one desk and Cadence is a work-hours
tool.

---

## Option 2 — Your computer, reachable from your phone

Same as option 1, but you also open it on your phone over your
home wifi, at an address like `http://192.168.1.5:8000`.

Costs nothing and takes about ten minutes. `serve.py` already
listens on `0.0.0.0`, which is the part that makes this possible —
so most of the work is done.

**Good:** free · phone access · data stays home.

**Bad:** same wifi only · laptop must be awake · home addresses
sometimes shift.

**Suits you if** you want it on your phone at home without paying
for or learning anything new.

---

## Option 3 — A small rented server ("VPS")

You rent a computer in a data centre for roughly **$4–6/month**.
It never sleeps. Cadence gets a real address you can reach from
anywhere.

Providers: Hetzner (cheapest), DigitalOcean (friendliest guides),
Vultr. All have Lagos-reachable regions; Hetzner's are in Europe,
about 100ms away — imperceptible for this.

**Good:** always on · works anywhere · genuinely yours · same
Linux commands you've already been using.

**Bad:** monthly cost · you're the sysadmin (updates, backups) ·
you'd want a domain and HTTPS, which is a few more steps.

**Suits you if** you want Cadence available everywhere and don't
mind an hour of setup plus occasional upkeep.

---

## Option 4 — A hosting platform (PythonAnywhere, Render, Fly.io)

You hand them your code and they run it. No server administration.

**Good:** no sysadmin work · HTTPS handled · free tiers exist.

**Bad — and this one matters for Cadence:** most free tiers **put
your app to sleep** after inactivity and **wipe the filesystem on
restart**. Cadence keeps everything in `cadence.db`, a file. On a
platform like that, your tasks can vanish on a redeploy.

Workable, but only with either a paid tier that has persistent
storage, or by moving from SQLite to their hosted database — real
work, and it would undo some of Phase 12.

**Suits you if** you want zero server admin and will pay for a
tier with persistent disk.

---

## What I'd suggest

**Option 2 now, option 3 when it earns it.**

Reasoning:

1. Cadence is single-user by your design — no accounts, no
   sharing. Nobody else needs to reach it, so a public address
   solves a problem you don't have yet.
2. The alarm still needs an open tab, so hosting doesn't unlock
   the feature you'd most want from it.
3. Option 2 is free and reversible. Use it for a couple of weeks
   and you'll know whether "I want this on my phone at the shops"
   is a real need or a hypothetical one.
4. If it becomes real, option 3 is a straight upgrade — same
   `deploy.sh`, same files, just a different computer.

Option 4 I'd actively avoid for now, purely because of the
disappearing-file problem. It fights the design instead of fitting
it.

---

## What's already built either way

None of this is blocked on the decision — the app is deploy-ready:

- `serve.py` — waitress, the production server. Handles several
  requests at once and doesn't hand out debug pages.
- `deploy.sh` — checks Python, checks packages, checks the
  database, **backs up your data**, runs the tests, verifies debug
  is off, then starts the server.
- `config.py` — development vs production. Production must be
  asked for explicitly; the app refuses to start in production
  through the dev command.
- `requirements.txt` — the two packages needed, pinned.
- Security headers, no debugger, no tracebacks shown to visitors.

Any of the four options runs this same code. The only question is
which computer.
