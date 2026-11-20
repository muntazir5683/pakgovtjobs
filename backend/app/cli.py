"""Operational CLI.

  python -m app.cli init-db                 create tables + sync sources.json
  python -m app.cli check-sources           ping every source URL (no DB / AI needed)
  python -m app.cli crawl [--source NAME]   run one crawl now
  python -m app.cli expire                  run the active -> expired transition now
"""
import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

from .crawler.fetch import FetchError, Http


def _check_one(src: dict) -> tuple[dict, str]:
    try:
        with Http() as http:
            f = http.get(src["url"], retries=0)
        return src, f"OK   {len(f.body):>8} bytes  {f.url}"
    except FetchError as e:
        return src, f"FAIL {str(e)[:110]}"


def _seed_demo() -> int:
    from datetime import timedelta

    from . import db, jobs_repo
    from .config import settings
    from .extractor import ExtractedJob
    from .timeutil import today_pkt

    today = today_pkt()
    with db.connection() as conn:
        src = conn.execute(
            """INSERT INTO sources (name, url, sector, province, is_active) VALUES
               ('DEMO DATA (not a real source)', 'demo://seed', 'Federal', 'All Pakistan', false)
               ON CONFLICT (url) DO UPDATE SET name = EXCLUDED.name RETURNING *"""
        ).fetchone()
    rows = [
        ("Assistant Director (BS-17)", "FPSC", "Federal", "Islamabad", "Master", 25, 12, "https://www.fpsc.gov.pk/"),
        ("Police Constable (BS-07)", "Punjab Police", "Police", "Punjab", "Matric", 1500, 2, "https://punjabpolice.gov.pk/"),
        ("Medical Officer (BS-17)", "Health Department KPK", "Medical", "Khyber Pakhtunkhwa", "MBBS/BDS", 80, 0, "https://www.dohkp.gov.pk/"),
        ("Soldier (GD) Induction", "Pakistan Army", "Armed Forces", "All Pakistan", "Matric", None, 30, "https://joinpakarmy.gov.pk/"),
        ("Junior Clerk (BS-11)", "SPSC", "Provincial", "Sindh", "Intermediate", 120, 5, "https://spsc.gov.pk/"),
        ("Test Invigilators", "NTS", "Testing", "All Pakistan", "Bachelor", None, 9, "https://www.nts.org.pk/"),
        ("Lecturer (BS-18) Computer Science", "PPSC", "Provincial", "Punjab", "MPhil/PhD", 40, -4, "https://ppsc.gop.pk/"),
        ("Sub Inspector", "Islamabad Police", "Police", "Islamabad", "Bachelor", 60, -20, "https://islamabadpolice.gov.pk/"),
    ]
    n = 0
    for title, dept, sector, prov, edu, posts, days, url in rows:
        job = ExtractedJob(
            title=title, department=dept, sector=sector, province=prov, education=f"{edu} (demo)",
            education_level=edu, total_posts=posts, last_date=today + timedelta(days=days),
            publish_date=today - timedelta(days=7),
        )
        n += jobs_repo.insert_job(
            job, source=src, page_url=f"demo://{title}", apply_url=url, ad_media_url=None,
            today=today, no_deadline_expire_days=settings.no_deadline_expire_days,
        )
    return n


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    sub.add_parser("check-sources")
    c = sub.add_parser("crawl")
    c.add_argument("--source", help="only sources whose name contains this text")
    d = sub.add_parser("discover", help="dry run: show candidate links found on sources (no DB, no AI)")
    d.add_argument("source", help="text contained in the source name, e.g. 'ppsc'")
    sub.add_parser("expire")
    sub.add_parser("seed-demo", help="insert fake sample jobs for UI development (no Gemini needed)")
    args = p.parse_args()

    if args.cmd == "check-sources":
        from .sources_registry import load_registry

        sources = load_registry()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(_check_one, sources))
        bad = 0
        for src, msg in results:
            bad += msg.startswith("FAIL")
            print(f"{src['name'][:42]:<42} {msg}")
        print(f"\n{len(results) - bad}/{len(results)} reachable")
        return 0

    if args.cmd == "discover":
        from .config import settings
        from .crawler.discover import extract_candidates
        from .crawler.runner import fetch_listing
        from .sources_registry import load_registry

        for src in load_registry():
            if args.source.lower() not in src["name"].lower():
                continue
            print(f"\n== {src['name']}  {src['url']}")
            try:
                with Http() as http:
                    html, base = fetch_listing(http, src["url"], src)
            except FetchError as e:
                print(f"   FAILED: {e}")
                continue
            cands = extract_candidates(html, base, settings.max_candidates_per_page)
            print(f"   {len(html)} bytes of HTML, {len(cands)} candidate(s)")
            for c in cands[:25]:
                print(f"   [{c.kind:5}] score={c.score} {c.title[:70]!r} -> {c.url[:110]}")
        return 0

    from . import db, lifecycle, sources_registry

    try:
        db.init_schema()
        if args.cmd == "init-db":
            print(f"Schema ready; {sources_registry.sync_sources()} sources synced")
        elif args.cmd == "crawl":
            from .crawler.runner import run_crawl

            print(run_crawl("cli", args.source) or "Crawl skipped (already running elsewhere)")
        elif args.cmd == "expire":
            print(f"{lifecycle.expire_jobs()} job(s) expired")
        elif args.cmd == "seed-demo":
            print(f"{_seed_demo()} demo job(s) inserted")
    finally:
        db.close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(main())
