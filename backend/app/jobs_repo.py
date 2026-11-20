"""Write-side helpers: hashing, slugs, dedup and inserts."""
import hashlib
import re
import unicodedata
from datetime import date

from . import db
from .extractor import ExtractedJob


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def link_hash(url: str, title: str) -> str:
    """SHA-256(url + title) - the dedup key required by the spec (title is case/space-normalized)."""
    return hashlib.sha256(f"{url.strip()}{_norm(title)}".encode("utf-8")).hexdigest()


def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-") or "job"


def make_slug(job: ExtractedJob, source_hash: str) -> str:
    base = slugify(f"{job.title} {job.department or ''}")
    return f"{base}-{source_hash[:8]}"


def unseen_hashes(hashes: list[str]) -> set[str]:
    """Return the subset of `hashes` that is in neither seen_links nor jobs."""
    if not hashes:
        return set()
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT link_hash AS h FROM seen_links WHERE link_hash = ANY(%s) "
            "UNION SELECT source_hash FROM jobs WHERE source_hash = ANY(%s)",
            (hashes, hashes),
        ).fetchall()
    known = {r["h"] for r in rows}
    return set(hashes) - known


def mark_seen(h: str, source_id: int, url: str, title: str, is_job: bool) -> None:
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO seen_links (link_hash, source_id, url, title, is_job) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (link_hash) DO NOTHING",
            (h, source_id, url, title[:500], is_job),
        )


def insert_job(
    job: ExtractedJob,
    *,
    source: dict,
    page_url: str,
    apply_url: str,
    ad_media_url: str | None,
    today: date,
    no_deadline_expire_days: int,
    parse_method: str = "ai",
) -> bool:
    """Insert one job. Returns False when it already existed (duplicate source_hash)."""
    source_hash = link_hash(page_url, job.title)
    publish = job.publish_date if job.publish_date and job.publish_date <= today else today

    if job.last_date is not None:
        expired = job.last_date < today
    else:
        expired = (today - publish).days > no_deadline_expire_days

    sector = job.sector or source["sector"]
    province = job.province or source["province"]
    if province == "All Pakistan" and source["province"] != "All Pakistan":
        province = source["province"]  # a Punjab Police ad is a Punjab ad even if the model said nationwide

    with db.connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO jobs (slug, source_hash, source_id, title, department, sector, province, education,
                              education_level, total_posts, publish_date, last_date, status,
                              official_apply_url, ad_media_url, parse_method)
            VALUES (%(slug)s, %(hash)s, %(source_id)s, %(title)s, %(department)s, %(sector)s, %(province)s,
                    %(education)s, %(education_level)s, %(total_posts)s, %(publish)s, %(last_date)s,
                    %(status)s, %(apply)s, %(media)s, %(method)s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            {
                "slug": make_slug(job, source_hash),
                "hash": source_hash,
                "source_id": source["id"],
                "title": job.title,
                "department": (job.department or "")[:300] or None,
                "sector": sector,
                "province": province,
                "education": (job.education or "")[:500] or None,
                "education_level": job.education_level,
                "total_posts": job.total_posts,
                "publish": publish,
                "last_date": job.last_date,
                "status": "expired" if expired else "active",
                "apply": apply_url,
                "media": ad_media_url,
                "method": parse_method,
            },
        )
        return cur.fetchone() is not None


def drop_fallback_jobs(source_id: int, urls: list[str]) -> int:
    """The AI has now extracted these ads properly: remove the rough non-AI rows for the same URLs."""
    with db.connection() as conn:
        cur = conn.execute(
            "DELETE FROM jobs WHERE parse_method = 'fallback' AND source_id = %s "
            "AND (official_apply_url = ANY(%s) OR ad_media_url = ANY(%s))",
            (source_id, urls, urls),
        )
        return cur.rowcount


def job_exists_for_url(source_id: int, url: str) -> bool:
    with db.connection() as conn:
        return conn.execute(
            "SELECT 1 FROM jobs WHERE source_id = %s AND (official_apply_url = %s OR ad_media_url = %s) LIMIT 1",
            (source_id, url, url),
        ).fetchone() is not None
