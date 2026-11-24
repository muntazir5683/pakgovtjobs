# PakGovJobs

Automated Pakistani government job aggregator. Crawls official sources every 6 hours,
extracts structured job data with Gemini Flash, publishes it, and moves jobs to **Expired** after the
deadline (Asia/Karachi time).

```
db/schema.sql            PostgreSQL schema (sources, jobs, seen_links)
db/schema_sqlite.sql     SQLite schema (local fallback when DATABASE_URL is unset)
backend/                 FastAPI + crawler + Gemini extractor + APScheduler
  sources.json           registry of official recruitment URLs
frontend/                Next.js (App Router, TypeScript, Tailwind) — /, /expired-jobs, /job/[slug], /admin
api/index.py             Vercel Python entrypoint (same FastAPI app under /api/*)
.github/workflows/       scheduled crawler (Playwright + Neon)
```

## Run it locally

### 1. Database
- **Easiest:** leave `DATABASE_URL` unset — the backend creates `backend/pakgovjobs.db` (SQLite).
- **Or** create a Neon/Supabase Postgres database and paste its connection string
  (`postgres://` and `postgresql://` both work; `postgres://` is normalized).

The schema is applied automatically on backend start (`db/schema.sql` / `schema_sqlite.sql` are idempotent).

### 2. Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
copy .env.example .env        # set GEMINI_API_KEY, ADMIN_PASSWORD, ADMIN_TOKEN_SECRET (+ DATABASE_URL if not using SQLite)
.\.venv\Scripts\python -m app.cli check-sources
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000   # ONE worker hosts the local scheduler
```

| Command | What it does |
| :-- | :-- |
| `python -m app.cli check-sources` | HTTP-checks every URL in `sources.json` (no DB / AI needed) |
| `python -m app.cli discover ppsc` | dry run: candidate links on matching sources |
| `python -m app.cli crawl --source ppsc` | one real crawl of matching sources |
| `python -m app.cli expire` | active → expired transition now |
| `python -m app.cli seed-demo` | 8 fake jobs for UI work without a Gemini key |

If port 8000 is taken, run uvicorn on another port and set `API_URL` in `frontend/.env.local`.

Local schedule (PKT, in-process via APScheduler): crawl at :15 every 6h, expiry nightly at 00:05.

### 3. Frontend
```powershell
cd frontend
npm install
copy .env.example .env.local      # API_URL=http://localhost:8000
npm run dev                       # http://localhost:3000
```

## Design notes

* **Dedup** — `source_hash = sha256(page_url + normalized title)`; `seen_links` remembers every evaluated URL.
* **JS-heavy / bot-blocking sites** — `"render": true` in `sources.json` forces Playwright; it is also used
  by default for listing pages when `RENDER_LISTINGS=true`. If Playwright/Chromium is missing, the crawler
  falls back to plain HTTP (required for the lightweight Vercel API bundle).
* **Lifecycle** — Available = `status='active' AND closing date >= today(PKT)`. Expired rows are never deleted.
* **Ads with no stated deadline** — `last_date` stays `NULL`; they expire `NO_DEADLINE_EXPIRE_DAYS` (default 45)
  after `publish_date`.
* **Admin** — `/admin` uses `ADMIN_PASSWORD`; the backend issues a signed 12 h token in an httpOnly cookie.

## Production (100% free): Vercel + Neon + GitHub Actions

No credit card required on the free tiers of all three.

### 1. Neon PostgreSQL
1. Create a free project at https://neon.tech and copy a connection string.
2. For **GitHub Actions** (crawler), use the **direct** (non-pooler) URL so `pg_try_advisory_lock` works.
3. For **Vercel** (API), the pooler URL is fine (and often better under serverless).

### 2. Vercel (frontend + API together)
1. https://vercel.com/new → import this GitHub repo. Leave **Root Directory** empty (repository root).
2. Framework / build are defined by root `vercel.json` (Next.js from `frontend/` + Python from `api/index.py`).
3. Project → Settings → Environment Variables:

   | Name | Value |
   | :-- | :-- |
   | `DATABASE_URL` | Neon URL (pooler OK) |
   | `ADMIN_PASSWORD` | strong password for `/admin` |
   | `ADMIN_TOKEN_SECRET` | long random string |
   | `CORS_ORIGINS` | `https://<your-vercel-domain>` (and preview URLs if needed) |
   | `DB_POOL_MAX` | `3` (optional) |

   Leave `API_URL` **unset** — the Next.js server calls the same deployment’s `/api/*`.
4. Deploy. Health check: `https://<your-app>.vercel.app/api/health`.

The Vercel Python function stays small (root `requirements.txt` has no Playwright/Chromium). It serves jobs
from Neon only; it does **not** run the crawler or APScheduler.

### 3. GitHub Actions (crawler every 6 hours)
1. Repo → Settings → Secrets and variables → Actions. Add:

   | Secret | Value |
   | :-- | :-- |
   | `DATABASE_URL` | Neon **direct** URL |
   | `GEMINI_API_KEY` | from https://aistudio.google.com/apikey |
   | `ADMIN_PASSWORD` | (optional, same as Vercel) |
   | `ADMIN_TOKEN_SECRET` | (optional) |

2. Workflow: `.github/workflows/crawl.yml` — cron `0 */6 * * *` (UTC) + **Run workflow** (manual), with an
   optional source filter.
3. First run: Actions → Crawl → Run workflow. Confirm new rows on the Vercel site / Neon console.

Optional: set Vercel `GITHUB_TOKEN` + `GITHUB_REPO` so the `/admin` “Run crawler” button dispatches this workflow.

Never commit `backend/.env`; secrets live only in Neon / Vercel / GitHub.

## Tests
```powershell
cd backend
.\.venv\Scripts\python -m pytest                       # SQLite fallback by default
$env:TEST_DATABASE_URL="postgresql://..."; .\.venv\Scripts\python -m pytest   # + Postgres (wipes that DB!)
```
