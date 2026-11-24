"""Crawl orchestration: sources -> candidate links -> AI extraction -> deduplicated inserts.

Failure isolation: one broken source (timeout, DNS, 404, TLS, bad HTML, AI error) is logged and
recorded on its `sources` row, and never stops the other sources.
"""
import hashlib
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import NamedTuple
from urllib.parse import urlparse

from .. import db, jobs_repo, lifecycle, sources_registry
from ..config import settings
from ..extractor import (
    ExtractionError,
    UnsupportedContent,
    api_key_configured,
    extract_jobs,
    media_part,
    text_part,
)
from ..timeutil import now_pkt, today_pkt
from . import fallback
from .discover import Candidate, extract_candidates, find_media_links
from .fetch import FetchError, Http, Fetched, guess_kind, html_to_text, looks_blocked, render_html

log = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = 727001
MIN_TEXT_CHARS = 300
MAX_CONSECUTIVE_FAILURES = 5

_run_lock = threading.Lock()
state: dict = {"running": False, "trigger": None, "started_at": None, "finished_at": None, "summary": None}

_IMAGE_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
               ".gif": "image/gif", ".bmp": "image/bmp"}


class AbortSource(Exception):
    """Stop processing the current source (e.g. AI key invalid, repeated failures)."""


# --------------------------------------------------------------------------- helpers

def _image_mime(f: Fetched) -> str:
    if f.content_type.startswith("image/"):
        return f.content_type
    path = urlparse(f.url).path.lower()
    for ext, mime in _IMAGE_MIME.items():
        if path.endswith(ext):
            return mime
    return "image/jpeg"


def _update_source(source_id: int, **fields) -> None:
    cols = ", ".join(f"{k} = %({k})s" for k in fields)
    with db.connection() as conn:
        conn.execute(f"UPDATE sources SET {cols} WHERE id = %(id)s", {**fields, "id": source_id})


def _valid_http_url(u: str | None) -> bool:
    if not u:
        return False
    p = urlparse(u.strip())
    return p.scheme in ("http", "https") and bool(p.netloc)


def fetch_listing(http: Http, url: str, opts: dict) -> tuple[str, str]:
    """Return (html, base_url) for a source's listing page.

    Dynamic portals only show their tables/links after JavaScript runs, so by default the page is
    rendered with Playwright first (RENDER_LISTINGS=true; a source can opt out with "render": false).
    Plain HTTP is the fallback / second opinion, and the richest non-blocked result wins."""
    want_render = opts["render"] if "render" in opts else settings.render_listings
    results: list[tuple[str, str]] = []
    errors: list[str] = []

    if want_render:
        try:
            results.append((render_html(url, paginate=True), url))
        except FetchError as e:
            errors.append(f"render: {e}")

    def usable(r: tuple[str, str]) -> bool:
        return looks_blocked(html_to_text(r[0])) is None

    good = [r for r in results if usable(r)]
    if not good or len(html_to_text(good[0][0])) < MIN_TEXT_CHARS:
        try:
            f = http.get(url)
            results.append((f.text or "", f.url))
        except FetchError as e:
            errors.append(f"http: {e}")

    good = [r for r in results if usable(r)]
    if good:
        return max(good, key=lambda r: len(html_to_text(r[0])))
    if results:  # everything we got was a firewall / error page
        reason = looks_blocked(html_to_text(results[0][0]))
        raise FetchError(f"Blocked by site firewall / page unavailable: {reason!r}")
    raise FetchError("; ".join(errors) or f"Could not load {url}")


# --------------------------------------------------------------------------- candidate processing

class Outcome(NamedTuple):
    status: str  # "job" | "nonjob" | "unchanged"
    inserted: int
    key: str  # seen_links key to record


def _content_key(cand: Candidate, text: str) -> str:
    """HTML pages change over time (index pages gain new ads), so their seen-key includes a digest of the
    page text. Digits/whitespace are stripped so counters and timestamps do not trigger re-extraction."""
    digest = hashlib.sha256(re.sub(r"[\d\s]+", "", text).encode()).hexdigest()[:16]
    return jobs_repo.link_hash(cand.url, f"{cand.title}|{digest}")


def _process_candidate(
    http: Http, source: dict, opts: dict, cand: Candidate, today: date, preloaded_html: str | None = None
) -> Outcome:
    """Raises FetchError/ExtractionError for transient problems (candidate is retried next run)."""
    key = jobs_repo.link_hash(cand.url, cand.title)
    parts: list[dict] = []
    ad_media_url: str | None = None
    page_url = cand.url
    kind = cand.kind

    fetched: Fetched | None = None
    html: str | None = preloaded_html
    if html is None:
        fetched = http.get(cand.url)
        kind = guess_kind(fetched.url, fetched.content_type)
        html = fetched.text

    if kind in ("pdf", "image"):
        assert fetched is not None
        mime = "application/pdf" if kind == "pdf" else _image_mime(fetched)
        parts.append(media_part(fetched.body, mime))
        ad_media_url = cand.url
    else:
        assert html is not None
        text = html_to_text(html)
        media_links = find_media_links(html, fetched.url if fetched else cand.url) if preloaded_html is None else []
        pdfs = [m for m in media_links if m.kind == "pdf"]
        ad_media_url = (pdfs or media_links or [None])[0].url if media_links else None

        if len(text) < MIN_TEXT_CHARS and preloaded_html is None and opts.get("render", True):
            try:  # detail page may be a JS shell
                html2 = render_html(cand.url)
                text2 = html_to_text(html2)
                if len(text2) > len(text):
                    text = text2
                    media_links = find_media_links(html2, cand.url)
                    pdfs = [m for m in media_links if m.kind == "pdf"]
                    ad_media_url = (pdfs or media_links or [None])[0].url if media_links else None
            except FetchError:
                pass

        key = _content_key(cand, text)
        if not jobs_repo.unseen_hashes([key]):
            return Outcome("unchanged", 0, key)  # same content as last time: no AI call

        parts.append(text_part(f"Page URL: {page_url}\n\n{text}"))
        if len(text) < MIN_TEXT_CHARS and ad_media_url:
            try:  # thin page whose real content is an attached ad
                m = http.get(ad_media_url)
                mk = guess_kind(m.url, m.content_type)
                if mk in ("pdf", "image"):
                    parts.append(media_part(m.body, "application/pdf" if mk == "pdf" else _image_mime(m)))
            except FetchError:
                pass
        elif len(text) < 80:
            return Outcome("nonjob", 0, key)

    hint = f"Source: {source['name']} ({source['sector']}, {source['province']}). Link text: {cand.title}"
    try:
        jobs = extract_jobs(parts, today, hint)
    except UnsupportedContent as e:
        log.info("Unsupported content %s: %s", cand.url, e)
        return Outcome("nonjob", 0, key)

    inserted = 0
    for job in jobs:
        apply_url = job.apply_url if _valid_http_url(job.apply_url) else (cand.url if kind == "html" else source["url"])
        if jobs_repo.insert_job(
            job,
            source=source,
            page_url=page_url,
            apply_url=apply_url,
            ad_media_url=ad_media_url,
            today=today,
            no_deadline_expire_days=settings.no_deadline_expire_days,
        ):
            inserted += 1
            log.info("  + [%s] %s", source["name"], job.title)
    if jobs:
        jobs_repo.drop_fallback_jobs(source["id"], list({cand.url, page_url}))
    return Outcome("job" if jobs else "nonjob", inserted, key)


def _run_fallback(source: dict, html: str, base: str, today: date, all_media: bool = False) -> int:
    """Non-AI extraction from the listing page. Returns the number of new jobs inserted."""
    inserted = 0
    for e in fallback.parse_listing(html, base, today, all_media):
        if not e.from_table_row and jobs_repo.job_exists_for_url(source["id"], e.url):
            continue  # already captured (by the AI or a previous fallback run)
        job = fallback.to_extracted_job(e, source).normalized()
        if jobs_repo.insert_job(
            job,
            source=source,
            page_url=e.url,
            apply_url=e.url,
            ad_media_url=e.url if e.kind in ("pdf", "image") else None,
            today=today,
            no_deadline_expire_days=settings.no_deadline_expire_days,
            parse_method="fallback",
        ):
            inserted += 1
            log.info("  + [%s] (fallback) %s", source["name"], job.title)
    return inserted


def crawl_source(source: dict, opts: dict, today: date) -> dict:
    t0 = time.monotonic()
    stats = {"source": source["name"], "links": 0, "new": 0, "failed": 0, "status": "ok", "error": None}
    _update_source(source["id"], last_status="running")
    deadline = t0 + settings.source_time_budget_seconds
    notes: list[str] = []

    try:
        with Http() as http:
            html, base = fetch_listing(http, source["url"], opts)
            # "media": "all" = this site posts its ads as banner images / PDF circulars with no keywords in
            # the file name (MES, FWO, NLC, ANF, ...): hand every non-icon image/PDF on the page to Gemini Vision.
            all_media = opts.get("media") == "all"
            candidates = extract_candidates(html, base, settings.max_candidates_per_page, accept_all_media=all_media)
            page_mode = opts.get("mode") == "page" or not candidates
            pages: dict[str, str] = {}

            if page_mode:
                # Listing itself is the ad (HTML table / banner notice): extract from the page text,
                # re-processing only when its content actually changes.
                page_cand = Candidate(url=source["url"], title="page", kind="html")
                candidates = [page_cand] + ([c for c in candidates] if opts.get("mode") == "page" else [])
                pages[page_cand.url] = html

            stats["links"] = len(candidates)
            # PDFs/images are immutable: skip the ones already seen without even downloading them.
            # HTML pages are re-fetched (cheap) and only sent to the AI when their content changed.
            media_keys = {c.url: jobs_repo.link_hash(c.url, c.title) for c in candidates if c.kind != "html"}
            fresh = jobs_repo.unseen_hashes(list(media_keys.values()))
            todo, html_n = [], 0
            for c in candidates:
                if c.kind == "html":
                    if html_n < settings.max_html_per_run:
                        todo.append(c)
                        html_n += 1
                elif media_keys[c.url] in fresh:
                    todo.append(c)
            ai_calls = 0

            consecutive = 0
            ai_failures = 0
            fallback_reason: str | None = None
            if not api_key_configured():
                fallback_reason = "GEMINI_API_KEY is not configured"
                todo = []  # nothing to send to the AI; the fallback parser reads the listing directly
            for cand in todo:
                if ai_calls >= settings.max_new_per_source:
                    notes.append("per-run AI cap reached; remaining candidates deferred to the next run")
                    break
                if time.monotonic() > deadline:
                    notes.append(f"time budget hit; {len(todo) - todo.index(cand)} candidate(s) deferred")
                    break
                try:
                    out = _process_candidate(http, source, opts, cand, today, pages.get(cand.url))
                except ExtractionError as e:
                    msg = str(e)
                    if "GEMINI_API_KEY" in msg or "auth failed" in msg:
                        fallback_reason = msg
                        break
                    ai_failures += 1
                    if ai_failures >= MAX_CONSECUTIVE_FAILURES:
                        fallback_reason = f"Gemini failing repeatedly: {msg[:120]}"
                        break
                    stats["failed"] += 1
                    consecutive += 1
                    notes.append(f"{cand.url}: {msg[:140]}")
                    log.warning("[%s] extraction failed for %s: %s", source["name"], cand.url, msg)
                except FetchError as e:
                    stats["failed"] += 1
                    consecutive += 1
                    notes.append(f"{cand.url}: {str(e)[:140]}")
                    log.warning("[%s] fetch failed for %s: %s", source["name"], cand.url, e)
                else:
                    consecutive = 0
                    ai_failures = 0
                    if out.status != "unchanged":
                        ai_calls += 1
                        stats["new"] += out.inserted
                        jobs_repo.mark_seen(out.key, source["id"], cand.url, cand.title, out.status == "job")
                if consecutive >= MAX_CONSECUTIVE_FAILURES:
                    raise AbortSource(f"{consecutive} consecutive failures")

            if fallback_reason:
                if not settings.fallback_parser:
                    raise AbortSource(fallback_reason)
                log.warning("[%s] AI unavailable (%s); using non-AI fallback parser", source["name"], fallback_reason)
                stats["new"] += _run_fallback(source, html, base, today, all_media)
                notes.insert(0, f"AI unavailable ({fallback_reason[:100]}); non-AI fallback parser used")
                stats["failed"] = max(stats["failed"], 1)  # surfaces as 'partial' in /admin
    except AbortSource as e:
        stats["status"], stats["error"] = "error", str(e)
    except FetchError as e:
        stats["status"], stats["error"] = "error", f"Unreachable: {e}"
        log.warning("[%s] listing unreachable: %s", source["name"], e)
    except Exception as e:  # never let one source crash the run
        stats["status"], stats["error"] = "error", f"{type(e).__name__}: {e}"
        log.exception("[%s] unexpected crawler error", source["name"])
    else:
        if stats["failed"]:
            stats["status"] = "partial"
        if notes:
            stats["error"] = "; ".join(notes[:3])[:1000]

    duration = int((time.monotonic() - t0) * 1000)
    try:
        _update_source(
            source["id"],
            last_crawled_at=datetime.now(now_pkt().tzinfo),
            last_status=stats["status"],
            last_error=stats["error"],
            last_links_found=stats["links"],
            last_new_jobs=stats["new"],
            last_duration_ms=duration,
        )
    except Exception:
        log.exception("Could not persist health for %s", source["name"])
    return stats


# --------------------------------------------------------------------------- public entry point

def run_crawl(trigger: str = "scheduler", source_filter: str | None = None) -> dict | None:
    """Crawl all active sources. Returns a summary, or None if a crawl is already running."""
    if not _run_lock.acquire(blocking=False):
        log.info("Crawl already running in this process; skipping (%s)", trigger)
        return None
    try:
        with db.connection() as lock_conn:
            if not db.try_advisory_lock(lock_conn, ADVISORY_LOCK_KEY):
                log.info("Another instance holds the crawl lock; skipping (%s)", trigger)
                return None
            try:
                return _run_locked(trigger, source_filter)
            finally:
                db.advisory_unlock(lock_conn, ADVISORY_LOCK_KEY)
    finally:
        _run_lock.release()


def _run_locked(trigger: str, source_filter: str | None) -> dict:
    started = now_pkt()
    state.update(running=True, trigger=trigger, started_at=started.isoformat(), finished_at=None)
    log.info("Crawl started (%s)", trigger)
    try:
        sources_registry.sync_sources()
        opts_by_url = sources_registry.registry_options()
        with db.connection() as conn:
            sources = conn.execute("SELECT * FROM sources WHERE is_active ORDER BY id").fetchall()
        # sources.json is the source of truth: rows removed from the file are no longer crawled.
        sources = [s for s in sources if s["url"] in opts_by_url]
        if source_filter:
            f = source_filter.lower()  # matches a source name or a whole sector ("banking", "development")
            sources = [s for s in sources if f in s["name"].lower() or f in s["sector"].lower()]
        today = today_pkt()

        def work(s: dict) -> dict:
            return crawl_source(s, opts_by_url.get(s["url"], {}), today)

        with ThreadPoolExecutor(max_workers=settings.max_concurrent_sources) as pool:
            results = list(pool.map(work, sources))

        expired = lifecycle.expire_jobs(today)
        summary = {
            "trigger": trigger,
            "sources": len(results),
            "ok": sum(r["status"] == "ok" for r in results),
            "partial": sum(r["status"] == "partial" for r in results),
            "errors": sum(r["status"] == "error" for r in results),
            "new_jobs": sum(r["new"] for r in results),
            "expired_now": expired,
            "seconds": round((now_pkt() - started).total_seconds(), 1),
        }
        log.info("Crawl finished: %s", summary)
        state["summary"] = summary
        return summary
    finally:
        state.update(running=False, finished_at=now_pkt().isoformat())
