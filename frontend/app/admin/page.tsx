import type { Metadata } from "next";
import { Suspense } from "react";
import { adminFetch, type AdminOverview, type AdminSource } from "@/lib/admin";
import { expireNow, logout, runCrawler, toggleSource } from "./actions";
import AutoRefresh from "./AutoRefresh";
import LoginForm from "./LoginForm";

export const metadata: Metadata = {
  title: "Admin",
  robots: { index: false, follow: false },
};

export default function AdminPage() {
  return (
    <Suspense fallback={<div className="h-64 animate-pulse rounded-xl bg-slate-200/70" />}>
      <AdminContent />
    </Suspense>
  );
}

const pkt = (iso: string | null | undefined) =>
  iso
    ? new Intl.DateTimeFormat("en-GB", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "Asia/Karachi",
      }).format(new Date(iso))
    : "never";

async function AdminContent() {
  const res = await adminFetch("/api/admin/overview");
  if (!res) return <LoginForm />;
  if (!res.ok) {
    return <p className="text-red-700">Admin API error ({res.status}). Is the backend running?</p>;
  }
  const o = (await res.json()) as AdminOverview;
  const running = o.crawler.running;
  const errors = o.sources.filter((s) => s.is_active && s.last_status === "error").length;
  const never = o.sources.filter((s) => s.is_active && !s.last_crawled_at).length;

  return (
    <div>
      <AutoRefresh active={running} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Crawler dashboard</h1>
          <p className="text-sm text-slate-600">Server time (PKT): {pkt(o.now_pkt)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <form action={runCrawler}>
            <button
              disabled={running}
              className="rounded-md bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {running ? "Crawler running…" : "Run Crawler Now"}
            </button>
          </form>
          <form action={expireNow}>
            <button className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
              Run expiry now
            </button>
          </form>
          <form action={logout}>
            <button className="rounded-md px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">Log out</button>
          </form>
        </div>
      </div>

      {o.gemini_configured === false && (
        <p role="alert" className="mt-4 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          GEMINI_API_KEY is not set on the backend — crawls can discover links but cannot extract jobs.
        </p>
      )}

      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Available jobs" value={o.counts.active} />
        <Stat label="Expired jobs" value={o.counts.expired} />
        <Stat label="Sources failing" value={errors} bad={errors > 0} />
        <Stat label="Never crawled" value={never} />
      </div>

      <section className="mt-5 rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-sm">
        <h2 className="font-semibold">Scheduler</h2>
        <ul className="mt-2 space-y-1 text-slate-700">
          <li>
            Status:{" "}
            <b>{running ? `running (${o.crawler.trigger}, since ${pkt(o.crawler.started_at)})` : "idle"}</b>
          </li>
          {o.schedule.github_actions_crawl ? (
            <li>Crawls run from GitHub Actions: {o.schedule.github_actions_crawl}</li>
          ) : (
            <>
              <li>Next crawl: {pkt(o.schedule.crawl_sources)}</li>
              <li>Next expiry (00:05 PKT): {pkt(o.schedule.expire_jobs)}</li>
            </>
          )}
          {o.crawler.summary && (
            <li>
              Last run ({pkt(o.crawler.finished_at)}):{" "}
              {Object.entries(o.crawler.summary)
                .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
                .join(" · ")}
            </li>
          )}
          {Object.keys(o.schedule).length === 0 && (
            <li className="text-amber-800">Scheduler is not running in this backend process (RUN_SCHEDULER=false).</li>
          )}
        </ul>
      </section>

      <div className="mt-5 overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Source</th>
              <th className="px-3 py-2">Sector</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Last crawled (PKT)</th>
              <th className="px-3 py-2 text-right">Links</th>
              <th className="px-3 py-2 text-right">New</th>
              <th className="px-3 py-2 text-right">Jobs</th>
              <th className="px-3 py-2">Error</th>
              <th className="px-3 py-2">Active</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {o.sources.map((s) => (
              <SourceRow key={s.id} s={s} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, bad }: { label: string; value: number; bad?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className={`text-2xl font-bold ${bad ? "text-red-700" : "text-slate-900"}`}>{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}

const STATUS_STYLE: Record<string, string> = {
  ok: "bg-emerald-100 text-emerald-800",
  partial: "bg-amber-100 text-amber-900",
  error: "bg-red-100 text-red-800",
  running: "bg-sky-100 text-sky-800",
};

function SourceRow({ s }: { s: AdminSource }) {
  return (
    <tr className={s.is_active ? "" : "bg-slate-50 text-slate-400"}>
      <td className="px-3 py-2">
        <a href={s.url} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
          {s.name}
        </a>
        <div className="text-xs text-slate-500">{s.province}</div>
      </td>
      <td className="px-3 py-2">{s.sector}</td>
      <td className="px-3 py-2">
        <span
          className={`rounded px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[s.last_status ?? ""] ?? "bg-slate-100 text-slate-600"}`}
        >
          {s.last_status ?? "pending"}
        </span>
      </td>
      <td className="px-3 py-2 whitespace-nowrap">{pkt(s.last_crawled_at)}</td>
      <td className="px-3 py-2 text-right">{s.last_links_found ?? "—"}</td>
      <td className="px-3 py-2 text-right">{s.last_new_jobs ?? "—"}</td>
      <td className="px-3 py-2 text-right">{s.total_jobs}</td>
      <td className="max-w-xs truncate px-3 py-2 text-xs text-red-700" title={s.last_error ?? ""}>
        {s.last_error}
      </td>
      <td className="px-3 py-2">
        <form action={toggleSource}>
          <input type="hidden" name="id" value={s.id} />
          <button className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100">
            {s.is_active ? "Pause" : "Resume"}
          </button>
        </form>
      </td>
    </tr>
  );
}
