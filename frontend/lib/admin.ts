import "server-only";
import { cookies } from "next/headers";
import { API_URL } from "./api";

export const ADMIN_COOKIE = "pgj_admin";

export type AdminSource = {
  id: number;
  name: string;
  url: string;
  sector: string;
  province: string;
  is_active: boolean;
  last_crawled_at: string | null;
  last_status: "ok" | "partial" | "error" | "running" | null;
  last_error: string | null;
  last_links_found: number | null;
  last_new_jobs: number | null;
  last_duration_ms: number | null;
  total_jobs: number;
};

export type AdminOverview = {
  now_pkt: string;
  crawler: {
    running: boolean;
    trigger: string | null;
    started_at: string | null;
    finished_at: string | null;
    summary: Record<string, number | string> | null;
  };
  schedule: Record<string, string | null>;
  gemini_configured: boolean;
  counts: { active: number; expired: number; total: number };
  sources: AdminSource[];
};

export async function adminToken(): Promise<string | undefined> {
  return (await cookies()).get(ADMIN_COOKIE)?.value;
}

/** Calls an admin endpoint with the session token. Returns null when unauthenticated. */
export async function adminFetch(path: string, init: RequestInit = {}): Promise<Response | null> {
  const token = await adminToken();
  if (!token) return null;
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: { ...init.headers, Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) return null;
  return res;
}
