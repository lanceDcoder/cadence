"""
=============================================================
  config.py  —  development vs production
=============================================================

WHY THIS FILE EXISTS

Running an app on your own laptop and running it on a real
server need OPPOSITE settings.

On your laptop you want the debugger: when something breaks,
you get an error page showing the exact line, and you can even
type Python into the browser to inspect what went wrong.

On a real server that same debugger is the single most
dangerous thing you can leave switched on. Anyone who reaches
the error page can run Python on your machine. Not "see your
data" — RUN CODE. It is the classic way small Flask apps get
taken over.

Verified on this app before the fix: sending
    {"goal": "x", "weeks": "abc"}
crashed the server and served the debugger. /console answered
HTTP 200.

So: one switch, one place. CADENCE_ENV decides everything.
"""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).parent
# Runtime data is kept beside the code locally. Hosted services can set
# CADENCE_DATA_DIR to a mounted persistent disk so schedules, accounts,
# logs, and the secret key survive redeployments.
DATA_DIR = Path(os.environ.get("CADENCE_DATA_DIR", BASE_DIR))


def _read_secret_key():
    """
    A secret key signs cookies so nobody can forge them.

    We don't use cookies yet (no login), but Flask wants one and
    later features will. Rules:

      1. If CADENCE_SECRET_KEY is set, use it.
      2. Otherwise generate one and save it to a file, so it
         survives restarts. A key that changes on every restart
         would log everyone out constantly.

    The key is NEVER written into the source code, because source
    code gets shared, copied and uploaded.
    """
    from_env = os.environ.get("CADENCE_SECRET_KEY")
    if from_env:
        return from_env

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_file = DATA_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()

    key = secrets.token_hex(32)
    key_file.write_text(key)
    try:
        key_file.chmod(0o600)      # only you can read it
    except OSError:
        pass
    return key


class Config:
    """Settings shared by both modes."""
    SECRET_KEY = _read_secret_key()

    # Reject absurdly large uploads before they reach our code.
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024        # 1 MB

    # Cookie hardening. Harmless now, correct later.
    SESSION_COOKIE_HTTPONLY = True              # JavaScript can't read it
    SESSION_COOKIE_SAMESITE = "Lax"             # blocks most CSRF

    APP_NAME = "Cadence"
    TIMEZONE = "Africa/Lagos"
    SNOOZE_MINUTES = 10
    ALARM_GRACE_MINUTES = 60


class DevelopmentConfig(Config):
    """Your laptop. Convenience over safety."""
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False               # no HTTPS locally


class ProductionConfig(Config):
    """A real server. Safety over convenience."""
    DEBUG = False                               # THE important line
    TESTING = False
    SESSION_COOKIE_SECURE = True                # HTTPS only
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_NAME = "cadence_session"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30  # 30 days


def get_config():
    """
    Pick the settings based on the CADENCE_ENV variable.

    Defaults to DEVELOPMENT deliberately. If someone forgets to
    set it, the worst case is a local app that is too chatty —
    not a public server running a debugger.

    Deployment sets CADENCE_ENV=production explicitly, and
    deploy.sh refuses to start without it.
    """
    env = os.environ.get("CADENCE_ENV", "development").lower()
    return ProductionConfig if env == "production" else DevelopmentConfig


def is_production():
    return os.environ.get("CADENCE_ENV", "").lower() == "production"


def validate_production_config():
    """Fail fast when production is missing a safe secret key."""
    if not is_production():
        return
    key = os.environ.get("CADENCE_SECRET_KEY", "").strip()
    if key and len(key) >= 32:
        return
    key_file = DATA_DIR / ".secret_key"
    if key_file.exists() and len(key_file.read_text().strip()) >= 32:
        return
    raise RuntimeError(
        "Production requires CADENCE_SECRET_KEY (32+ characters) "
        "or a private .secret_key file."
    )
