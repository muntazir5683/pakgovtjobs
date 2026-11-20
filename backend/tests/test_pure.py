import time
from datetime import date

from app import api
from app.crawler.discover import extract_candidates, site_key
from app.crawler.fetch import guess_kind, html_to_text
from app.extractor import ExtractedJob
from app.jobs_repo import link_hash, make_slug, slugify
from app.taxonomy import normalize_education_level, normalize_province, normalize_sector
from app.timeutil import PKT, today_pkt


def test_link_hash_is_stable_and_title_normalized():
    a = link_hash("https://x.gov.pk/ad.pdf", "Assistant  Director")
    b = link_hash("https://x.gov.pk/ad.pdf", " assistant director ")
    assert a == b and len(a) == 64
    assert a != link_hash("https://x.gov.pk/ad2.pdf", "Assistant Director")


def test_slug():
    assert slugify("Assistant Director (BS-17) & Co.") == "assistant-director-bs-17-co"
    assert slugify("اردو") == "job"
    j = ExtractedJob(title="Constable Police", department="Punjab Police")
    assert make_slug(j, "abcdef1234567890").endswith("-abcdef12")


def test_timezone_is_pkt():
    assert str(PKT) == "Asia/Karachi"
    assert today_pkt() == __import__("datetime").datetime.now(PKT).date()


def test_normalizers():
    assert normalize_sector("health") == "Medical"
    assert normalize_province("KPK") == "Khyber Pakhtunkhwa"
    assert normalize_education_level("BS in CS (16 years)") == "Bachelor"
    assert normalize_education_level("MSc Physics") == "Master"
    assert normalize_education_level("MBBS") == "MBBS/BDS"
    assert normalize_education_level("Matric") == "Matric"
    assert normalize_education_level("F.Sc") == "Intermediate"
    assert normalize_education_level("Bachelor degree") == "Bachelor"
    assert normalize_education_level("weird") == "Other"


def test_extracted_job_lenient_parsing():
    j = ExtractedJob.model_validate(
        {"title": "  Clerk  ", "last_date": "2026-12-31T00:00", "total_posts": "12", "sector": "police"}
    ).normalized()
    assert j.last_date == date(2026, 12, 31) and j.total_posts == 12 and j.sector == "Police"
    bad = ExtractedJob.model_validate({"title": "x", "last_date": "soon", "total_posts": "many"})
    assert bad.last_date is None and bad.total_posts is None


def test_site_key():
    assert site_key("https://www.fpsc.gov.pk/jobs") == "fpsc.gov.pk"
    assert site_key("https://sub.ppsc.gop.pk/") == "ppsc.gop.pk"
    assert site_key("https://www.nts.org.pk/") == "nts.org.pk"


HTML = """
<html><body>
<a href="/jobs/123">Assistant Director Vacancy</a>
<a href="/files/ad-constable.pdf">Download</a>
<a href="/files/annual.pdf">Annual Report</a>
<a href="/results">Final Result</a>
<a href="https://facebook.com/fpsc">Facebook jobs</a>
<a href="https://other.com/jobs">Jobs elsewhere</a>
<a href="https://cdn.other.com/jobs-advert.jpg">Advert</a>
<a href="mailto:a@b.c">jobs mail</a>
<img src="/img/logo-jobs.png" alt="logo">
<img src="/img/recruitment-ad-nov.jpg" alt="Recruitment ad">
</body></html>
"""


def test_candidate_discovery():
    cands = {c.url: c for c in extract_candidates(HTML, "https://www.fpsc.gov.pk/")}
    assert "https://www.fpsc.gov.pk/jobs/123" in cands            # same-site keyword html
    assert "https://cdn.other.com/jobs-advert.jpg" in cands       # external image allowed when keyworded
    assert "https://www.fpsc.gov.pk/img/recruitment-ad-nov.jpg" in cands
    assert "https://www.fpsc.gov.pk/results" not in cands         # negative keyword
    assert "https://other.com/jobs" not in cands                  # external html
    assert not any("facebook" in u for u in cands)
    assert not any(u.endswith(".pdf") for u in cands)             # un-keyworded PDFs on a non-jobs page
    assert not any("logo" in u for u in cands)
    assert not any(u.startswith("mailto") for u in cands)


def test_candidates_accept_all_pdfs_on_jobs_page():
    cands = {c.url for c in extract_candidates(HTML, "https://www.fpsc.gov.pk/careers")}
    assert "https://www.fpsc.gov.pk/files/ad-constable.pdf" in cands      # any PDF on a careers page
    assert "https://www.fpsc.gov.pk/files/annual.pdf" not in cands        # negative text still wins


def test_kind_and_text():
    assert guess_kind("https://a/b.PDF?x=1") == "pdf"
    assert guess_kind("https://a/b.jpg") == "image"
    assert guess_kind("https://a/b", "application/pdf") == "pdf"
    assert guess_kind("https://a/b.aspx") == "html"
    assert "hello" in html_to_text("<form><nav>x</nav><p>hello</p><script>1</script></form>")


def test_html_content_key_ignores_digits_but_not_new_text():
    from app.crawler.discover import Candidate
    from app.crawler.runner import _content_key

    c = Candidate(url="https://x.gov.pk/jobs", title="Jobs", kind="html")
    base = _content_key(c, "Visitors: 1234\nClerk BS-11 last date 05-12-2026")
    assert base == _content_key(c, "Visitors:  9999\nClerk BS-11 last date 06-12-2026")  # counters / dates
    assert base != _content_key(c, "Visitors: 1234\nClerk BS-11 last date 05-12-2026\nNurse BS-16")  # new ad


def test_salvage_truncated_gemini_output():
    from app.extractor import _salvage_truncated

    raw = '{"is_job_ad": true, "jobs": [{"title": "A"}, {"title": "B", "total_posts": 3}, {"title": "C", "tot'
    out = _salvage_truncated(raw)
    assert [j["title"] for j in out["jobs"]] == ["A", "B"]
    assert _salvage_truncated('{"is_job_ad": true') is None


def test_placeholder_key_is_treated_as_unconfigured(monkeypatch):
    import pytest as _pt

    from app import extractor
    from app.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "PASTE_YOUR_GEMINI_API_KEY_HERE")
    with _pt.raises(extractor.ExtractionError, match="GEMINI_API_KEY is not configured"):
        extractor._post({})


def test_block_page_detection():
    from app.crawler.fetch import looks_blocked

    assert looks_blocked("The URL you requested has been blocked\nWeb Page Blocked!\nAttack ID: 2000")
    assert looks_blocked("Page Not Available\nPlease try again later.")
    assert looks_blocked("Latest jobs " * 300 + " captcha") is None  # long real page is never flagged
    assert looks_blocked("Welcome to the Commission. Jobs. Careers. Results.") is None


def test_admin_token_roundtrip():
    t = api.make_token()
    assert api.verify_token(t)
    assert not api.verify_token(t[:-3] + "xyz")
    assert not api.verify_token("garbage")


def test_serialize_lifecycle_flags():
    today = date(2026, 11, 20)
    base = dict(status="active", last_date=date(2026, 11, 22), closes_on=date(2026, 11, 22))
    s = api._serialize(dict(base), today)
    assert s["days_left"] == 2 and s["closing_soon"] and not s["is_expired"]
    # last day: still available
    s = api._serialize(dict(status="active", last_date=today, closes_on=today), today)
    assert s["days_left"] == 0 and not s["is_expired"]
    # day after the deadline: expired even if the nightly job has not run yet
    s = api._serialize(dict(status="active", last_date=date(2026, 11, 19), closes_on=date(2026, 11, 19)), today)
    assert s["is_expired"] and s["expired_on"] == date(2026, 11, 19) and s["days_left"] is None
    # no deadline: not "closing soon", no countdown
    s = api._serialize(dict(status="active", last_date=None, closes_on=date(2026, 12, 20)), today)
    assert s["days_left"] is None and not s["deadline_known"] and not s["is_expired"]



FALLBACK_HTML = """
<html><body>
<nav><a href="/jobs">Jobs</a></nav>
<table>
 <tr><td><a href="/ads/adv-08.pdf">Advertisement 08/26</a></td><td>Closing dt: 23.11.2026</td></tr>
 <tr><td><a href="/ads/adv-02.pdf">Advertisement 02/26</a></td><td>Closed</td></tr>
 <tr><td><a href="/ads/old.pdf">Recruitment advertisement 2019 (clerks)</a></td><td></td></tr>
 <tr><td><a href="/jobs/rules.pdf">Recruitment Rules 2023</a></td><td></td></tr>
 <tr><td><a href="/jobs/sign-in">Sign In</a></td></tr>
</table>
<ul><li><a href="/jobs/driver">Download</a> Driver (BS-04) - 3 posts - last date 5 Dec 2026</li></ul>
</body></html>
"""


def test_fallback_parser_extracts_posts_and_skips_noise():
    from app.crawler import fallback

    today = date(2026, 11, 20)
    by_title = {e.title: e for e in fallback.parse_listing(FALLBACK_HTML, "https://x.gov.pk/jobs/", today)}
    assert by_title["Advertisement 08/26"].last_date == date(2026, 11, 23)
    assert by_title["Advertisement 02/26"].last_date < today          # site marks it Closed
    assert by_title["Recruitment advertisement 2019 (clerks)"].last_date.year == 2019  # old ad -> expired
    drv = next(e for t, e in by_title.items() if t.startswith("Driver"))
    assert drv.last_date == date(2026, 12, 5) and drv.total_posts == 3
    assert not any("Rules" in t or "Sign In" in t or t == "Jobs" for t in by_title)


def test_fallback_date_classification():
    from app.crawler.fallback import classify_dates

    today = date(2026, 11, 20)
    assert classify_dates("Posted 01-11-2026 last date 30/11/2026", today) == (date(2026, 11, 1), date(2026, 11, 30))
    assert classify_dates("Closing date: 25 Nov 2026", today) == (None, date(2026, 11, 25))
    assert classify_dates("Published November 3, 2026", today) == (date(2026, 11, 3), None)
    assert classify_dates("no dates here", today) == (None, None)


def test_api_key_configured_helper(monkeypatch):
    from app import extractor
    from app.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "PASTE_YOUR_GEMINI_API_KEY_HERE")
    assert not extractor.api_key_configured()
    monkeypatch.setattr(settings, "gemini_api_key", "AIzaSyRealLookingKey")
    assert extractor.api_key_configured()


def test_render_follows_pagination():
    """Playwright listing render walks every 'Next' page and merges them (no listings skipped)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from app.crawler.fetch import render_html

    def page(n: int) -> str:
        nxt = f'<li class="next"><a href="/p{n + 1}">Next</a></li>' if n < 3 else '<li class="next disabled"><a>Next</a></li>'
        return (f"<html><body><a href='/ad{n}.pdf'>Advertisement {n}/26 vacancies</a>"
                f"<ul class='pagination'>{nxt}</ul></body></html>")

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            n = int(self.path.lstrip("/p") or 1) if self.path.startswith("/p") else 1
            body = page(n).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        html = render_html(f"http://127.0.0.1:{srv.server_address[1]}/", paginate=True)
    finally:
        srv.shutdown()
    for n in (1, 2, 3):
        assert f"/ad{n}.pdf" in html


def test_new_sectors_are_valid_and_normalized():
    from app.taxonomy import SECTORS
    from app.extractor import SYSTEM_PROMPT

    assert "Development & Societies" in SECTORS and "Banking & Finance" in SECTORS
    assert normalize_sector("Banking") == "Banking & Finance"
    assert normalize_sector("Banking & Finance") == "Banking & Finance"
    assert normalize_sector("Housing Society") == "Development & Societies"
    assert normalize_sector("development authority") == "Development & Societies"
    assert "Banking & Finance" in SYSTEM_PROMPT and "__SECTORS__" not in SYSTEM_PROMPT


def test_registry_sectors_are_all_valid():
    from app.config import settings
    from app.sources_registry import load_registry
    from app.taxonomy import SECTORS
    import json

    raw = json.loads(settings.sources_file.read_text(encoding="utf-8-sig"))["sources"]
    assert len(load_registry()) == len(raw)          # nothing silently skipped for a bad sector/province
    assert {e["sector"] for e in raw} <= set(SECTORS)
