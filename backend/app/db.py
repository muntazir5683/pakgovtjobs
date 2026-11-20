"""Synchronous psycopg3 pool.

The backend is deliberately synchronous: Playwright needs a Proactor event loop on Windows while
psycopg's async mode needs a Selector loop, so plain threads avoid that conflict entirely.
"""
import logging
from contextlib import contextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

log = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).resolve().parent.parent.parent / "db" / "schema.sql"

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=12,
            # prepare_threshold=None keeps this compatible with PgBouncer/Supabase pooler connection strings
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            open=False,
        )
        _pool.open(wait=True, timeout=20)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection():
    with get_pool().connection() as conn:
        yield conn


def init_schema() -> None:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with connection() as conn:
        conn.execute(sql)
    log.info("Database schema ensured")
