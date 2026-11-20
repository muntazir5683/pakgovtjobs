# PakGovJobs

Automated Pakistani government job aggregator (see the SRDS). Crawls official sources every 6 hours,
extracts structured job data with Gemini Flash, publishes it, and moves jobs to **Expired** after the
deadline (Asia/Karachi time).

```
db/schema.sql          PostgreSQL schema (sources, jobs, seen_links)
backend/               FastAPI + crawler + Gemini extractor + APScheduler
  sources.json         registry of official recruitment URLs
frontend/              Next.js (App Router, TypeScript, Tailwind) — /, /expired-jobs, /job/[slug], /admin
```

## Run it

### 1. Database
Create a Supabase/Neon project (or local Postgres) and copy its connection string. The schema is
applied automatically on backend start (`db/schema.sql` is idempotent).

### 2. Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
copy .env.example .env        # set DATABASE_URL, GEMINI_API_KEY, ADMIN_PASSWORD, ADMIN_TOKEN_SECRET
.\.venv\Scripts\python -m app.cli check-sources    # which source URLs are reachable (no DB/AI needed)
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000   # run ONE worker: it hosts the scheduler
```
Useful commands:

| Command | What it does |
| :-- | :-- |
| `python -m app.cli check-sources` | HTTP-checks every URL in `sources.json` (no DB / AI needed) |
| `python -m app.cli discover ppsc` | dry run: shows the candidate links found on matching sources (no DB / AI) |
| `python -m app.cli crawl --source ppsc` | one real crawl of matching sources |
| `python -m app.cli expire` | run the active → expired transition now |
| `python -m app.cli seed-demo` | insert 8 fake jobs so you can see the UI without a Gemini key |

If port 8000 is taken on your machine, run uvicorn on another port and set `API_URL` in `frontend/.env.local`.

Schedule (PKT, in-process via APScheduler): crawl at 00:15 / 06:15 / 12:15 / 18:15, expiry nightly at
00:05. On startup the backend also runs the expiry once, so a restart after midnight self-heals.

### 3. Frontend
```powershell
cd frontend
copy .env.example .env.local   # API_URL=http://localhost:8000
npm install
npm run dev                    # http://localhost:3000   (admin: /admin)
```

## Behaviour worth knowing

* **Dedup** — `source_hash = sha256(url + normalized title)`, `UNIQUE`. Every evaluated link is also
  stored in `seen_links`: PDFs/images are never re-downloaded or re-sent to Gemini; HTML pages are
  re-fetched each run but only re-sent when their text changed (digits ignored), so index pages that
  gain new ads are picked up.
* **Crawl depth** — one level: the listing page, plus each job/PDF/image link found on it. Pages that
  turn out to be index pages are read as a whole (Gemini returns every job on them).
* **JS-heavy / bot-blocking sites** — `"render": true` in `sources.json` forces Playwright; it is also used
  automatically when plain HTTP returns almost no text or an HTTP error/connection reset.
* **Failure isolation** — each source is crawled in its own try/except; an unreachable site is logged on
  its `sources` row (`last_status/last_error`) and the crawl continues. Visible on `/admin`.
* **Lifecycle** — Available = `status='active' AND closing date >= today(PKT)`; the API applies the date
  check too, so there is no 00:00–00:05 gap. Expired rows are never deleted.
* **Ads with no stated deadline** — `last_date` stays `NULL` and the card says "Deadline not stated".
  They count as closed `NO_DEADLINE_EXPIRE_DAYS` (default 45) after `publish_date`.
* **Cost control** — at most `MAX_NEW_PER_SOURCE` (15) new candidates per source per run go to Gemini, so a
  first run over a backlog spreads across several 6-hourly runs instead of one huge bill.
* **Admin** — `/admin` logs in against `ADMIN_PASSWORD`; the backend issues a signed 12 h token stored in an
  httpOnly cookie. Set strong values for `ADMIN_PASSWORD` / `ADMIN_TOKEN_SECRET` before deploying.

## Tests
```powershell
cd backend
.\.venv\Scripts\python -m pytest                       # unit tests
$env:TEST_DATABASE_URL="postgresql://..."; .\.venv\Scripts\python -m pytest   # + end-to-end (TRUNCATEs that DB!)
```
