"""Active -> expired transition. Expired rows are never deleted."""
import logging
from datetime import date

from . import db
from .config import settings
from .timeutil import today_pkt

log = logging.getLogger(__name__)


def expire_jobs(today: date | None = None) -> int:
    """Mark jobs whose deadline is before `today` (PKT) as expired. Idempotent."""
    today = today or today_pkt()
    with db.connection() as conn:
        cur = conn.execute(
            f"""
            UPDATE jobs
               SET status = 'expired'
             WHERE status = 'active'
               AND (
                    last_date < %(today)s
                 OR (last_date IS NULL AND {db.add_days("publish_date", "%(grace)s")} < %(today)s)
               )
            """,
            {"today": today, "grace": settings.no_deadline_expire_days},
        )
        n = cur.rowcount
    log.info("Lifecycle: %s job(s) moved to expired (today PKT = %s)", n, today)
    return n
