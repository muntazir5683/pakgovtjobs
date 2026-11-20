import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import lifecycle
from .config import settings
from .crawler import runner
from .timeutil import PKT

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _safe_expire() -> None:
    try:
        lifecycle.expire_jobs()
    except Exception:
        log.exception("Nightly expiry failed")


def _safe_crawl() -> None:
    try:
        runner.run_crawl("scheduler")
    except Exception:
        log.exception("Scheduled crawl failed")


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    sched = BackgroundScheduler(timezone=PKT)
    # Every night at 00:05 PKT: active -> expired.
    sched.add_job(
        _safe_expire,
        CronTrigger(hour=0, minute=5, timezone=PKT),
        id="expire_jobs",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=6 * 3600,
    )
    # Every N hours (default 6) at :15 PKT -> 00:15, 06:15, 12:15, 18:15 (after the nightly expiry).
    sched.add_job(
        _safe_crawl,
        CronTrigger(hour=f"*/{settings.crawl_interval_hours}", minute=15, timezone=PKT),
        id="crawl_sources",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    sched.start()
    _scheduler = sched
    log.info("Scheduler started (crawl every %sh at :15 PKT, expiry nightly 00:05 PKT)", settings.crawl_interval_hours)

    # Catch-up: if the server was down at 00:05, fix statuses right away.
    threading.Thread(target=_safe_expire, name="expire-on-start", daemon=True).start()
    if settings.crawl_on_startup:
        threading.Thread(target=_safe_crawl, name="crawl-on-start", daemon=True).start()


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_runs() -> dict[str, str | None]:
    if _scheduler is None:
        return {}
    out = {}
    for job in _scheduler.get_jobs():
        out[job.id] = job.next_run_time.isoformat() if job.next_run_time else None
    return out
