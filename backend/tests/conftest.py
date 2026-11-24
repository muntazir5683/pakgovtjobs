import os
import tempfile
from pathlib import Path

# Must be set before `app.*` is imported anywhere.
os.environ.setdefault("RUN_SCHEDULER", "false")
os.environ.setdefault("ADMIN_PASSWORD", "test-pass")
os.environ.setdefault("ADMIN_TOKEN_SECRET", "test-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("GEMINI_MIN_INTERVAL_SECONDS", "0")
if os.environ.get("TEST_DATABASE_URL"):
    # PostgreSQL (the database is wiped by the tests!)
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
else:
    # No TEST_DATABASE_URL: run the whole suite against a throwaway SQLite file (the local-dev fallback).
    _tmp = Path(tempfile.mkdtemp(prefix="pakgovjobs-test-")) / "test.db"
    os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.as_posix()
