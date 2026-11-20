"""End-to-end tests against a real PostgreSQL (set TEST_DATABASE_URL; the DB is TRUNCATEd!).

The Gemini call and the government websites are replaced by a local HTTP server and a canned
extractor response, so the whole pipeline (discover -> fetch -> extract -> dedup -> insert ->
expire -> API) runs for real.
"""
import json
import os
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")

from fastapi.testclient import TestClient  # noqa: E402

from app import db, extractor, jobs_repo, lifecycle, sources_registry  # noqa: E402
from app.config import settings  # noqa: E402
from app.crawler import runner  # noqa: E402
from app.extractor import ExtractedJob  # noqa: E402
from app.main import app  # noqa: E402
from app.timeutil import today_pkt  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _close_pool_at_end():
    yield
    db.close_pool()


@pytest.fixture(autouse=True)
def clean_db():
    db.init_schema()
    with db.connection() as conn:
        conn.execute("TRUNCATE jobs, seen_links, sources RESTART IDENTITY CASCADE")
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        # app startup synced the real sources.json; tests want a blank slate
        with db.connection() as conn:
            conn.execute("TRUNCATE jobs, seen_links, sources RESTART IDENTITY CASCADE")
        yield c


def _source(name="Test Source", url="http://127.0.0.1:1/", sector="Federal", province="All Pakistan") -> dict:
    with db.connection() as conn:
        return conn.execute(
            "INSERT INTO sources (name, url, sector, province) VALUES (%s,%s,%s,%s) RETURNING *",
            (name, url, sector, province),
        ).fetchone()


def _job(source, title, last_date, publish=None, **kw) -> bool:
    today = today_pkt()
    page_url = kw.pop("page_url", f"http://x/{title.strip().lower()}")
    return jobs_repo.insert_job(
        ExtractedJob(title=title, last_date=last_date, publish_date=publish, sector="Federal", province="Punjab",
                     education_level=kw.pop("education_level", "Bachelor"), department=kw.pop("department", "Dept"),
                     **kw),
        source=source,
        page_url=page_url,
        apply_url="http://x/apply",
        ad_media_url=None,
        today=today,
        no_deadline_expire_days=settings.no_deadline_expire_days,
    )


def test_dedup_by_hash():
    s = _source()
    assert _job(s, "Clerk", date.today() + timedelta(days=5)) is True
    assert _job(s, "Clerk", date.today() + timedelta(days=5)) is False
    assert _job(s, "  clerk ", date.today() + timedelta(days=5)) is False  # normalized title
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 1


def test_lifecycle_expiry_boundaries_and_no_delete():
    s = _source()
    t = today_pkt()
    _job(s, "Yesterday", t - timedelta(days=1))
    _job(s, "Today", t)
    _job(s, "Tomorrow", t + timedelta(days=1))
    # no deadline, published long ago / recently
    _job(s, "OldNoDeadline", None, publish=t - timedelta(days=settings.no_deadline_expire_days + 2))
    _job(s, "NewNoDeadline", None, publish=t)

    with db.connection() as conn:
        status = {r["title"]: r["status"] for r in conn.execute("SELECT title,status FROM jobs").fetchall()}
    # Inserting an already-past job stores it expired straight away.
    assert status["Yesterday"] == "expired" and status["OldNoDeadline"] == "expired"
    assert status["Today"] == "active" and status["Tomorrow"] == "active" and status["NewNoDeadline"] == "active"

    # Simulate the clock advancing 2 days at 00:05 PKT.
    n = lifecycle.expire_jobs(t + timedelta(days=2))
    assert n == 2  # Today + Tomorrow; NewNoDeadline is still inside its grace window
    with db.connection() as conn:
        status = {r["title"]: r["status"] for r in conn.execute("SELECT title,status FROM jobs").fetchall()}
        total = conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"]
    assert status["Today"] == "expired" and status["Tomorrow"] == "expired"
    assert status["NewNoDeadline"] == "active"
    assert total == 5  # nothing deleted


def test_public_api_lists_filters_and_detail(client):
    s = _source()
    t = today_pkt()
    _job(s, "Open Soon", t + timedelta(days=2), department="FPSC")
    _job(s, "Open Later", t + timedelta(days=20), education_level="Master")
    _job(s, "Closed", t - timedelta(days=3))

    r = client.get("/api/jobs").json()
    assert {j["title"] for j in r["items"]} == {"Open Soon", "Open Later"}
    soon = next(j for j in r["items"] if j["title"] == "Open Soon")
    assert soon["days_left"] == 2 and soon["closing_soon"] and not soon["is_expired"]

    r = client.get("/api/jobs", params={"status": "expired"}).json()
    assert [j["title"] for j in r["items"]] == ["Closed"]
    assert r["items"][0]["is_expired"] and r["items"][0]["expired_on"] == (t - timedelta(days=3)).isoformat()

    assert client.get("/api/jobs", params={"education": "Master"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"sector": "Police"}).json()["total"] == 0
    assert client.get("/api/jobs", params={"province": "Punjab", "q": "fpsc"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"q": "100%"}).json()["total"] == 0  # wildcard is escaped

    d = client.get(f"/api/jobs/{soon['slug']}").json()
    assert d["title"] == "Open Soon" and d["source"]["name"] == "Test Source"
    assert client.get("/api/jobs/nope").status_code == 404


def test_job_past_deadline_hidden_even_before_nightly_job(client):
    """00:00-00:05 gap: status is still 'active' but last_date < today must not show as available."""
    s = _source()
    t = today_pkt()
    _job(s, "Stale", t + timedelta(days=1))
    with db.connection() as conn:
        conn.execute("UPDATE jobs SET last_date = %s WHERE title = 'Stale'", (t - timedelta(days=1),))
    assert client.get("/api/jobs").json()["total"] == 0
    assert client.get("/api/jobs", params={"status": "expired"}).json()["total"] == 1


def test_admin_auth_and_overview(client):
    assert client.get("/api/admin/overview").status_code == 401
    assert client.post("/api/admin/crawl").status_code == 401
    assert client.post("/api/admin/login", json={"password": "bad"}).status_code == 401
    tok = client.post("/api/admin/login", json={"password": "test-pass"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    _source()
    o = client.get("/api/admin/overview", headers=h).json()
    assert o["counts"]["total"] == 0 and len(o["sources"]) == 1


# ---------------------------------------------------------------- full crawl pipeline

LISTING = """<html><body><h1>Careers</h1><p>{pad}</p>
<a href="/job/clerk">Clerk vacancy 2026</a>
<a href="/ads/constable.pdf">Constable recruitment advert</a>
<a href="/news">Latest news</a>
</body></html>""".replace("{pad}", "x " * 200)

DETAIL = "<html><body><h1>Clerk BS-11</h1><p>" + "Applications are invited for the post of Clerk. " * 20 + "</p></body></html>"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        routes = {
            "/": ("text/html", LISTING.encode()),
            "/job/clerk": ("text/html", DETAIL.encode()),
            "/ads/constable.pdf": ("application/pdf", b"%PDF-1.4 fake"),
        }
        if self.path in routes:
            ctype, body = routes[self.path]
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture()
def gov_site():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_full_crawl_pipeline_with_failure_isolation(gov_site, monkeypatch, tmp_path, client):
    t = today_pkt()
    calls: list[str] = []

    def fake_post(payload):
        parts = payload["contents"][0]["parts"]
        has_pdf = any("inline_data" in p for p in parts)
        calls.append("pdf" if has_pdf else "html")
        if has_pdf:
            job = {"title": "Constable", "department": "Punjab Police", "sector": "Police", "province": "Punjab",
                   "education_level": "Matric", "total_posts": 500,
                   "last_date": (t + timedelta(days=10)).isoformat()}
        else:
            job = {"title": "Clerk BS-11", "department": "FPSC", "sector": "Federal", "province": "Islamabad",
                   "education_level": "Intermediate", "last_date": (t - timedelta(days=1)).isoformat()}
        return {"candidates": [{"content": {"parts": [{"text": json.dumps({"is_job_ad": True, "jobs": [job]})}]}}]}

    monkeypatch.setattr(extractor, "_post", fake_post)
    # no Playwright in tests: listing has plenty of text so no render fallback is triggered
    reg = tmp_path / "sources.json"
    reg.write_text(json.dumps({"sources": [
        {"name": "Dead Site", "url": "http://127.0.0.1:1/", "sector": "Federal"},
        {"name": "Live Site", "url": gov_site + "/", "sector": "Federal"},
    ]}))
    monkeypatch.setattr(settings, "sources_file", reg)

    summary = runner.run_crawl("test")
    assert summary["sources"] == 2 and summary["errors"] == 1 and summary["new_jobs"] == 2

    with db.connection() as conn:
        src = {r["name"]: r for r in conn.execute("SELECT * FROM sources").fetchall()}
        jobs = {r["title"]: r for r in conn.execute("SELECT * FROM jobs").fetchall()}
    assert src["Dead Site"]["last_status"] == "error" and "Unreachable" in src["Dead Site"]["last_error"]
    assert src["Live Site"]["last_status"] == "ok" and src["Live Site"]["last_new_jobs"] == 2
    assert src["Live Site"]["last_crawled_at"] is not None

    assert jobs["Constable"]["status"] == "active"
    assert jobs["Constable"]["ad_media_url"].endswith("/ads/constable.pdf")
    assert jobs["Constable"]["province"] == "Punjab"
    assert jobs["Clerk BS-11"]["status"] == "expired"                      # deadline already passed
    assert jobs["Clerk BS-11"]["official_apply_url"].endswith("/job/clerk")  # falls back to the page URL

    # Second run: nothing new, nothing re-sent to the AI.
    n_calls = len(calls)
    summary2 = runner.run_crawl("test")
    assert summary2["new_jobs"] == 0 and len(calls) == n_calls
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 2

    # And the API reflects the lifecycle split.
    assert [j["title"] for j in client.get("/api/jobs").json()["items"]] == ["Constable"]
    assert [j["title"] for j in client.get("/api/jobs", params={"status": "expired"}).json()["items"]] == ["Clerk BS-11"]


def test_gemini_key_missing_uses_fallback_parser(gov_site, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "gemini_api_key", "PASTE_YOUR_GEMINI_API_KEY_HERE")
    reg = tmp_path / "s.json"
    reg.write_text(json.dumps({"sources": [{"name": "Live", "url": gov_site + "/", "sector": "Federal"}]}))
    monkeypatch.setattr(settings, "sources_file", reg)
    summary = runner.run_crawl("test")
    assert summary["new_jobs"] == 2 and summary["errors"] == 0
    with db.connection() as conn:
        rows = conn.execute("SELECT title, status, parse_method FROM jobs ORDER BY title").fetchall()
        assert conn.execute("SELECT count(*) AS n FROM seen_links").fetchone()["n"] == 0  # AI redoes them later
        s = conn.execute("SELECT last_status, last_error FROM sources").fetchone()
    assert [r["title"] for r in rows] == ["Clerk vacancy 2026", "Constable recruitment advert"]
    assert all(r["parse_method"] == "fallback" and r["status"] == "active" for r in rows)
    assert s["last_status"] == "partial" and "fallback" in s["last_error"]
    assert runner.run_crawl("test")["new_jobs"] == 0  # re-running does not duplicate


def test_gemini_key_missing_aborts_source_when_fallback_disabled(gov_site, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "fallback_parser", False)
    reg = tmp_path / "s.json"
    reg.write_text(json.dumps({"sources": [{"name": "Live", "url": gov_site + "/", "sector": "Federal"}]}))
    monkeypatch.setattr(settings, "sources_file", reg)
    summary = runner.run_crawl("test")
    assert summary["errors"] == 1 and summary["new_jobs"] == 0
    with db.connection() as conn:
        s = conn.execute("SELECT last_status, last_error FROM sources").fetchone()
        assert conn.execute("SELECT count(*) AS n FROM seen_links").fetchone()["n"] == 0  # retried next run
    assert s["last_status"] == "error" and "GEMINI_API_KEY" in s["last_error"]


def test_registry_sync_keeps_manual_pause(tmp_path, monkeypatch):
    reg = tmp_path / "s.json"
    reg.write_text(json.dumps({"sources": [{"name": "A", "url": "http://a.gov.pk/", "sector": "Police"}]}))
    monkeypatch.setattr(settings, "sources_file", reg)
    sources_registry.sync_sources()
    with db.connection() as conn:
        conn.execute("UPDATE sources SET is_active = false")
    sources_registry.sync_sources()  # file doesn't mention is_active -> admin pause is preserved
    with db.connection() as conn:
        assert conn.execute("SELECT is_active FROM sources").fetchone()["is_active"] is False

