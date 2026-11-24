"""Database access: PostgreSQL (psycopg3 pool) in production, SQLite as a zero-setup local fallback.

All SQL in the app is written once, in psycopg style (``%s`` / ``%(name)s`` placeholders). On SQLite a thin
wrapper translates that dialect (placeholders, ``ILIKE``, ``now()``, ``::int`` casts) and returns dict rows, so the
rest of the code does not care which backend is in use. Dialect differences that can't be translated textually
(date arithmetic, advisory locks, bulk ``= ANY(...)``) go through the small helpers at the bottom of this file.

The backend is deliberately synchronous: Playwright needs a Proactor event loop on Windows while
psycopg's async mode needs a Selector loop, so plain threads avoid that conflict entirely.
"""
import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)

IS_SQLITE = settings.is_sqlite

_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "db"
SCHEMA_FILE = _SCHEMA_DIR / ("schema_sqlite.sql" if IS_SQLITE else "schema.sql")

_pool = None  # psycopg_pool.ConnectionPool (PostgreSQL only)
_pool_lock = threading.Lock()


# --------------------------------------------------------------------------- PostgreSQL

def get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg.rows import dict_row
                from psycopg_pool import ConnectionPool

                pool = ConnectionPool(
                    settings.database_url,
                    min_size=1,
                    max_size=settings.db_pool_max,
                    # prepare_threshold=None keeps this compatible with PgBouncer (Neon "-pooler" / Supabase pooler).
                    kwargs={"row_factory": dict_row, "prepare_threshold": None},
                    # Neon scales to zero and closes idle connections: validate a connection before handing it out.
                    check=ConnectionPool.check_connection,
                    open=False,
                )
                pool.open(wait=True, timeout=30)
                _pool = pool
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# --------------------------------------------------------------------------- SQLite

def _sqlite_path() -> str:
    # sqlite:///relative.db  |  sqlite:////abs/posix.db  |  sqlite:///C:/abs/windows.db  |  sqlite:///:memory:
    return settings.database_url[len("sqlite:///"):] or ":memory:"


def _to_date(b: bytes) -> date | None:
    s = b.decode()[:10]
    return date.fromisoformat(s) if s else None


def _to_datetime(b: bytes) -> datetime | None:
    s = b.decode()
    return datetime.fromisoformat(s) if s else None


sqlite3.register_adapter(datetime, lambda d: d.isoformat(sep=" "))
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_converter("DATE", _to_date)
sqlite3.register_converter("TIMESTAMPTZ", _to_datetime)
sqlite3.register_converter("BOOLEAN", lambda b: b not in (b"0", b""))

_PLACEHOLDER = re.compile(r"%%|%\((\w+)\)s|%s")
_PG_CAST = re.compile(r"::\w+")
_ILIKE = re.compile(r"\bILIKE\b", re.IGNORECASE)
_NOW = re.compile(r"\bnow\(\)", re.IGNORECASE)


def _translate(sql: str) -> str:
    """psycopg-style SQL -> sqlite3 SQL (named params become :name, positional become ?)."""
    sql = _PG_CAST.sub("", sql)
    sql = _ILIKE.sub("LIKE", sql)
    sql = _NOW.sub("CURRENT_TIMESTAMP", sql)

    def repl(m: re.Match) -> str:
        if m.group(0) == "%%":
            return "%"
        return f":{m.group(1)}" if m.group(1) else "?"

    return _PLACEHOLDER.sub(repl, sql)


class _Result:
    """Eagerly fetched statement result (so no statement is left open when the transaction commits)."""

    def __init__(self, rows: list[dict], rowcount: int):
        self._rows = rows
        self.rowcount = rowcount

    def fetchone(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict]:
        return self._rows


def _dict_factory(cur: sqlite3.Cursor, row: tuple) -> dict:
    return {d[0]: v for d, v in zip(cur.description, row)}


class _SqliteConn:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(self, sql: str, params=None) -> _Result:
        cur = self._conn.execute(_translate(sql), params if params is not None else ())
        rows = cur.fetchall() if cur.description else []
        return _Result(rows, cur.rowcount)


def _sqlite_connect() -> sqlite3.Connection:
    path = _sqlite_path()
    if path != ":memory:":
        Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False)
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the crawler's writes
    except sqlite3.DatabaseError:
        pass
    return conn


# --------------------------------------------------------------------------- common API

@contextmanager
def connection():
    """Yield a connection with `.execute(sql, params)`; commits on success, rolls back on error."""
    if IS_SQLITE:
        raw = _sqlite_connect()
        try:
            yield _SqliteConn(raw)
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            raw.close()
    else:
        with get_pool().connection() as conn:
            yield conn


def init_schema() -> None:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    if IS_SQLITE:
        raw = _sqlite_connect()
        try:
            raw.executescript(sql)
        finally:
            raw.close()
    else:
        with connection() as conn:
            conn.execute(sql)
    log.info("Database schema ensured (%s)", "SQLite" if IS_SQLITE else "PostgreSQL")


_ready = False
_ready_lock = threading.Lock()


def ensure_ready() -> None:
    """Create the tables if the database is empty. Cheap after the first successful call.

    Used by the API (notably on Vercel, where there is no startup hook worth relying on), so a fresh Neon
    database works even before the first crawl has run.
    """
    global _ready
    if _ready:
        return
    with _ready_lock:
        if _ready:
            return
        with connection() as conn:
            if IS_SQLITE:
                exists = conn.execute("SELECT 1 AS x FROM sqlite_master WHERE type = 'table' AND name = 'jobs'").fetchone()
            else:
                exists = conn.execute("SELECT to_regclass('public.jobs') AS x").fetchone()["x"]
        if not exists:
            init_schema()
        _ready = True


# --------------------------------------------------------------------------- dialect helpers

def add_days(column: str, days_param: str) -> str:
    """SQL for `column + <days>` where `days_param` is a placeholder such as '%(grace)s'."""
    if IS_SQLITE:
        return f"date({column}, '+' || {days_param} || ' days')"
    return f"({column} + {days_param}::int)"


def in_placeholders(n: int) -> str:
    """'%s,%s,%s' for `col IN (...)`. Portable replacement for `col = ANY(%s)`."""
    return ",".join(["%s"] * n)


def try_advisory_lock(conn, key: int) -> bool:
    """Cross-process lock (PostgreSQL). SQLite is a single-machine dev fallback: the in-process lock suffices."""
    if IS_SQLITE:
        return True
    return bool(conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (key,)).fetchone()["ok"])


def advisory_unlock(conn, key: int) -> None:
    if not IS_SQLITE:
        conn.execute("SELECT pg_advisory_unlock(%s)", (key,))


def as_date(value) -> date:
    """Computed columns (e.g. COALESCE(...)) come back as ISO text on SQLite; normalize to `date`."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
