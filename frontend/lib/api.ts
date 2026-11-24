// Backend base URL (only ever read on the server, so it stays private).
//  1. API_URL (or NEXT_PUBLIC_API_URL) when set - e.g. http://127.0.0.1:8010 locally, or an external backend.
//  2. On Vercel the FastAPI backend is deployed in the same project under /api, so default to this deployment's
//     own origin (the production domain on production, the deployment URL on previews).
//  3. Otherwise the local dev backend.
function resolveApiUrl(): string {
  const explicit = process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL;
  if (explicit) return explicit;
  const host =
    process.env.VERCEL_ENV === "production"
      ? (process.env.VERCEL_PROJECT_PRODUCTION_URL ?? process.env.VERCEL_URL)
      : process.env.VERCEL_URL;
  if (host) return `https://${host}`;
  return "http://localhost:8000";
}

export const API_URL = resolveApiUrl().replace(/\/+$/, "");

export type Job = {
  id: number;
  slug: string;
  title: string;
  department: string | null;
  sector: string;
  province: string;
  education: string | null;
  education_level: string | null;
  total_posts: number | null;
  publish_date: string; // YYYY-MM-DD
  last_date: string | null; // YYYY-MM-DD
  status: "active" | "expired";
  official_apply_url: string;
  ad_media_url: string | null;
  created_at: string;
  // computed by the API in PKT
  is_expired: boolean;
  expired_on: string | null;
  deadline_known: boolean;
  days_left: number | null;
  closing_soon: boolean;
  source?: { name: string; url: string } | null;
};

export type JobsPage = {
  items: Job[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  today_pkt: string;
};

export type JobQuery = {
  status: "active" | "expired";
  q?: string;
  sector?: string;
  province?: string;
  education?: string;
  sort?: string;
  page?: number;
};

export async function fetchJobs(query: JobQuery): Promise<JobsPage> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const res = await fetch(`${API_URL}/api/jobs?${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Jobs API responded ${res.status}`);
  return res.json();
}

export async function fetchJob(slug: string): Promise<Job | null> {
  const res = await fetch(`${API_URL}/api/jobs/${encodeURIComponent(slug)}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Job API responded ${res.status}`);
  return res.json();
}
