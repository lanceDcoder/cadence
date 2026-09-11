"""
=============================================================
  serve.py  —  running Cadence for real
=============================================================

WHAT'S WRONG WITH `python3 app.py`?

That starts Flask's DEVELOPMENT server. Flask prints a warning
about it every time, and the warning is honest:

  - it handles one request at a time, so a slow request blocks
    everything else
  - it is not hardened against malformed or hostile requests
  - it prioritises helpful error messages over safety

Perfect while you build. Wrong for anything permanent.

WHAT THIS USES INSTEAD

Waitress: a production WSGI server. "WSGI" is just the agreed
way Python web apps talk to web servers.

  - handles many requests at once (threads)
  - written to survive hostile input
  - pure Python, so it works the same on Windows, Mac and Linux

Alternatives and why not:
  gunicorn  - excellent, very common, but Unix only (no Windows)
  uWSGI     - powerful, considerably more complex to configure
  waitress  - simplest thing that is genuinely production-grade

Start it with:   ./deploy.sh
Or directly:     CADENCE_ENV=production python3 serve.py
"""

import logging
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent


def setup_logging():
    """
    Write what happens to a file.

    In production nobody is watching a terminal. When something
    breaks at 3am you need a record, so errors go to
    logs/cadence.log as well as the screen.
    """
    # On hosted platforms this is the persistent data directory.
    import config
    log_dir = config.DATA_DIR / "logs"
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")

    file_handler = logging.FileHandler(log_dir / "cadence.log")
    file_handler.setFormatter(fmt)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console)

    return log_dir / "cadence.log"


def main():
    # Refuse to run without the production flag. Silently starting
    # in debug mode on a public server is exactly the accident this
    # whole file exists to prevent.
    if os.environ.get("CADENCE_ENV", "").lower() != "production":
        print()
        print("  CADENCE_ENV is not set to 'production'.")
        print()
        print("  Run it like this:")
        print("      CADENCE_ENV=production python3 serve.py")
        print()
        print("  Or just use:  ./deploy.sh")
        print()
        return 1

    log_path = setup_logging()

    # Imported AFTER the environment is set, so app.py picks up
    # the production config.
    from waitress import serve

    import storage
    from app import app

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    threads = int(os.environ.get("THREADS", 4))

    # Fail loudly at startup rather than mysteriously later.
    storage.init_db()
    health = storage.integrity_check()
    if health != "ok":
        logging.error("Database integrity check failed: %s", health)
        return 1

    stats = storage.stats()

    print()
    print("  " + "=" * 52)
    print("   Cadence — production server")
    print("  " + "=" * 52)
    print(f"   address   http://{host}:{port}")
    print(f"   threads   {threads}")
    print(f"   debug     OFF  (safe)")
    print(f"   database  {stats['total']} tasks, "
          f"{stats['routines']} routines, {stats['goals']} goals")
    print(f"   integrity {health}")
    print(f"   log file  {log_path}")
    print("  " + "=" * 52)
    print("   Ctrl+C to stop")
    print()

    logging.info("Cadence starting on %s:%s with %s threads",
                 host, port, threads)

    serve(app, host=host, port=port, threads=threads,
          ident="Cadence",              # don't advertise the server version
          max_request_body_size=1048576)  # 1 MB, matches Flask's limit
    return 0


if __name__ == "__main__":
    sys.exit(main())
