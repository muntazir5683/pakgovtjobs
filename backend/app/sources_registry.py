"""Keeps the `sources` table in sync with sources.json (matched by url)."""
import json
import logging

from . import db
from .config import settings
from .taxonomy import PROVINCES, SECTORS

log = logging.getLogger(__name__)


def load_registry() -> list[dict]:
    data = json.loads(settings.sources_file.read_text(encoding="utf-8-sig"))  # tolerate a BOM from Windows editors
    entries = data["sources"] if isinstance(data, dict) else data
    valid = []
    for e in entries:
        if e.get("sector") not in SECTORS:
            log.warning("Skipping source %r: invalid sector %r", e.get("name"), e.get("sector"))
            continue
        if e.get("province", "All Pakistan") not in PROVINCES:
            log.warning("Skipping source %r: invalid province %r", e.get("name"), e.get("province"))
            continue
        valid.append(e)
    return valid


def sync_sources() -> int:
    """Upsert registry entries. Existing `is_active` is only overridden if the file sets it explicitly."""
    entries = load_registry()
    with db.connection() as conn:
        for e in entries:
            conn.execute(
                """
                INSERT INTO sources (name, url, sector, province, is_active)
                VALUES (%(name)s, %(url)s, %(sector)s, %(province)s, %(is_active)s)
                ON CONFLICT (url) DO UPDATE
                   SET name = EXCLUDED.name,
                       sector = EXCLUDED.sector,
                       province = EXCLUDED.province,
                       is_active = CASE WHEN %(explicit)s THEN EXCLUDED.is_active ELSE sources.is_active END
                """,
                {
                    "name": e["name"],
                    "url": e["url"],
                    "sector": e["sector"],
                    "province": e.get("province", "All Pakistan"),
                    "is_active": e.get("is_active", True),
                    "explicit": "is_active" in e,
                },
            )
        if entries:
            # sources.json is the source of truth: drop rows for URLs that were removed/replaced.
            # Their jobs are kept (jobs.source_id is set to NULL). Demo seed data is left alone.
            urls = [e["url"] for e in entries]
            conn.execute(
                f"DELETE FROM sources WHERE url NOT IN ({db.in_placeholders(len(urls))}) AND url NOT LIKE 'demo://%%'",
                urls,
            )
    return len(entries)


def registry_options() -> dict[str, dict]:
    """Per-url crawl options that live only in sources.json (not in the DB schema)."""
    return {e["url"]: e for e in load_registry()}
