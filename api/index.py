"""Vercel serverless entrypoint for the FastAPI backend.

Vercel routes `/api/*` here (see root `vercel.json`). The FastAPI router already uses the `/api`
prefix, so paths like `/api/jobs` match as-is. Playwright/Chromium are not installed in this
runtime — the API never crawls; GitHub Actions does.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Set before any `app.*` import (Settings is cached on first load).
os.environ.setdefault("VERCEL", "1")
os.environ.setdefault("RUN_SCHEDULER", "false")
os.environ.setdefault("CRAWL_ON_STARTUP", "false")
os.environ.setdefault("DB_POOL_MAX", "3")
os.environ.setdefault("RENDER_LISTINGS", "false")  # no browser in the serverless bundle

from app.main import app  # noqa: E402

__all__ = ["app"]
