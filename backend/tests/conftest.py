import os

# Must be set before `app.*` is imported anywhere.
os.environ.setdefault("RUN_SCHEDULER", "false")
os.environ.setdefault("ADMIN_PASSWORD", "test-pass")
os.environ.setdefault("ADMIN_TOKEN_SECRET", "test-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("GEMINI_MIN_INTERVAL_SECONDS", "0")
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
