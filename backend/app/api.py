import base64
import hashlib
import hmac
import threading
import time
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from . import db, scheduler
from .config import settings
from .crawler import runner
from .taxonomy import EDUCATION_LEVELS, PROVINCES, SECTORS
from .timeutil import now_pkt, today_pkt

router = APIRouter(prefix="/api")

CLOSING_SOON_DAYS = 3

JOB_COLUMNS = """
    id, slug, title, department, sector, province, education, education_level, total_posts,
    publish_date, last_date, status, official_apply_url, ad_media_url, created_at,
    COALESCE(last_date, publish_date + %(grace)s::int) AS closes_on
"""
CLOSES_ON = "COALESCE(last_date, publish_date + %(grace)s::int)"


# ------------------------------------------------------------------ serialization

def _serialize(row: dict, today: date) -> dict:
    closes_on: date = row.pop("closes_on")
    expired = row["status"] == "expired" or closes_on < today
    days_left = None if expired or row["last_date"] is None else (row["last_date"] - today).days
    row.update(
        is_expired=expired,
        expired_on=closes_on if expired else None,
        deadline_known=row["last_date"] is not None,
        days_left=days_left,
        closing_soon=days_left is not None and days_left <= CLOSING_SOON_DAYS,
    )
    return row


def _like(term: str) -> str:
    esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


# ------------------------------------------------------------------ public endpoints

@router.get("/health")
def health() -> dict:
    with db.connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True, "today_pkt": today_pkt().isoformat(), "now_pkt": now_pkt().isoformat()}


@router.get("/filters")
def filters() -> dict:
    return {"sectors": SECTORS, "provinces": PROVINCES, "education_levels": EDUCATION_LEVELS}


@router.get("/jobs")
def list_jobs(
    status: Literal["active", "expired"] = "active",
    q: str | None = Query(None, max_length=100),
    sector: str | None = None,
    province: str | None = None,
    education: str | None = None,
    sort: Literal["newest", "closing"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
) -> dict:
    today = today_pkt()
    params: dict = {"today": today, "grace": settings.no_deadline_expire_days}
    where: list[str] = []

    if status == "active":
        where.append(f"status = 'active' AND {CLOSES_ON} >= %(today)s")
        order = f"{CLOSES_ON} ASC, id DESC" if sort == "closing" else "publish_date DESC, id DESC"
    else:
        where.append(f"(status = 'expired' OR {CLOSES_ON} < %(today)s)")
        order = f"{CLOSES_ON} DESC, id DESC"

    if sector:
        where.append("sector = %(sector)s")
        params["sector"] = sector
    if province:
        where.append("province = %(province)s")
        params["province"] = province
    if education:
        where.append("education_level = %(education)s")
        params["education"] = education
    if q:
        for i, term in enumerate(q.split()[:6]):
            params[f"q{i}"] = _like(term)
            where.append(
                f"(title ILIKE %(q{i})s OR department ILIKE %(q{i})s OR education ILIKE %(q{i})s)"
            )

    where_sql = " AND ".join(where)
    params.update(limit=page_size, offset=(page - 1) * page_size)
    with db.connection() as conn:
        total = conn.execute(f"SELECT count(*) AS n FROM jobs WHERE {where_sql}", params).fetchone()["n"]
        rows = conn.execute(
            f"SELECT {JOB_COLUMNS} FROM jobs WHERE {where_sql} ORDER BY {order} LIMIT %(limit)s OFFSET %(offset)s",
            params,
        ).fetchall()
    return {
        "items": [_serialize(r, today) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
        "today_pkt": today.isoformat(),
    }


@router.get("/jobs/{slug}")
def get_job(slug: str) -> dict:
    today = today_pkt()
    with db.connection() as conn:
        row = conn.execute(
            f"SELECT {JOB_COLUMNS}, source_id FROM jobs WHERE slug = %(slug)s",
            {"slug": slug, "grace": settings.no_deadline_expire_days},
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Job not found")
        src = None
        if row["source_id"]:
            src = conn.execute("SELECT name, url FROM sources WHERE id = %s", (row["source_id"],)).fetchone()
    job = _serialize(row, today)
    job["source"] = src
    return job


# ------------------------------------------------------------------ admin auth

def _sign(payload: str) -> str:
    return hmac.new(settings.admin_token_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    exp = str(int(time.time()) + settings.admin_token_ttl_hours * 3600)
    return base64.urlsafe_b64encode(f"{exp}.{_sign(exp)}".encode()).decode()


def verify_token(token: str) -> bool:
    try:
        exp, sig = base64.urlsafe_b64decode(token.encode()).decode().split(".", 1)
        return hmac.compare_digest(sig, _sign(exp)) and int(exp) > time.time()
    except Exception:
        return False


def require_admin(authorization: str | None = Header(None)) -> None:
    if not authorization or not authorization.lower().startswith("bearer ") or not verify_token(authorization[7:]):
        raise HTTPException(401, "Unauthorized")


class LoginBody(BaseModel):
    password: str


@router.post("/admin/login")
def admin_login(body: LoginBody) -> dict:
    time.sleep(0.4)  # blunt brute-force speed bump
    if not hmac.compare_digest(body.password.encode(), settings.admin_password.encode()):
        raise HTTPException(401, "Wrong password")
    return {"token": make_token(), "expires_in": settings.admin_token_ttl_hours * 3600}


# ------------------------------------------------------------------ admin endpoints

@router.get("/admin/overview", dependencies=[Depends(require_admin)])
def admin_overview() -> dict:
    today = today_pkt()
    with db.connection() as conn:
        sources = conn.execute(
            """
            SELECT s.*, (SELECT count(*) FROM jobs j WHERE j.source_id = s.id) AS total_jobs
              FROM sources s ORDER BY s.sector, s.name
            """
        ).fetchall()
        counts = conn.execute(
            f"""
            SELECT count(*) FILTER (WHERE status = 'active' AND {CLOSES_ON} >= %(today)s) AS active,
                   count(*) FILTER (WHERE status = 'expired' OR {CLOSES_ON} < %(today)s) AS expired,
                   count(*) AS total
              FROM jobs
            """,
            {"today": today, "grace": settings.no_deadline_expire_days},
        ).fetchone()
    return {
        "now_pkt": now_pkt().isoformat(),
        "crawler": runner.state,
        "schedule": scheduler.next_runs(),
        "gemini_configured": bool(settings.gemini_api_key.strip())
        and not settings.gemini_api_key.strip().upper().startswith("PASTE_"),
        "counts": counts,
        "sources": sources,
    }


@router.post("/admin/crawl", status_code=202, dependencies=[Depends(require_admin)])
def admin_crawl(source: str | None = Query(None, description="Only crawl sources whose name contains this")) -> dict:
    if runner.state["running"]:
        raise HTTPException(409, "A crawl is already running")
    threading.Thread(
        target=runner.run_crawl, args=("manual", source), name="manual-crawl", daemon=True
    ).start()
    return {"started": True}


@router.post("/admin/expire", dependencies=[Depends(require_admin)])
def admin_expire() -> dict:
    from . import lifecycle

    return {"expired": lifecycle.expire_jobs()}


@router.post("/admin/sources/{source_id}/toggle", dependencies=[Depends(require_admin)])
def admin_toggle_source(source_id: int) -> dict:
    with db.connection() as conn:
        row = conn.execute(
            "UPDATE sources SET is_active = NOT is_active WHERE id = %s RETURNING id, is_active", (source_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Source not found")
    return row
