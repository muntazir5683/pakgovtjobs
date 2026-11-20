import { fetchJobs } from "@/lib/api";
import FilterBar from "./FilterBar";
import JobCard from "./JobCard";
import Pagination from "./Pagination";

type SP = Promise<Record<string, string | string[] | undefined>>;

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";

/** Request-time component: reads searchParams, so callers must render it inside <Suspense>. */
export default async function JobsView({
  status,
  basePath,
  searchParams,
}: {
  status: "active" | "expired";
  basePath: string;
  searchParams: SP;
}) {
  const sp = await searchParams;
  const values = {
    q: one(sp.q).trim(),
    sector: one(sp.sector),
    province: one(sp.province),
    education: one(sp.education),
  };
  const pageNum = Math.max(1, parseInt(one(sp.page), 10) || 1);
  const data = await fetchJobs({ status, ...values, page: pageNum });

  return (
    <>
      <FilterBar action={basePath} values={values} />

      <p className="mt-5 text-sm text-slate-600" aria-live="polite">
        {data.total === 0
          ? "No jobs match your filters."
          : `${data.total.toLocaleString("en-US")} ${status === "active" ? "open" : "closed"} job${data.total === 1 ? "" : "s"}`}
      </p>

      <div className="mt-3 grid gap-4 md:grid-cols-2">
        {data.items.map((job) => (
          <JobCard key={job.id} job={job} />
        ))}
      </div>

      <Pagination basePath={basePath} params={values} page={data.page} pages={data.pages} />
    </>
  );
}

export function ListSkeleton() {
  return (
    <div aria-busy="true" className="animate-pulse">
      <div className="h-24 rounded-xl bg-slate-200/70" />
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-48 rounded-xl bg-slate-200/70" />
        ))}
      </div>
    </div>
  );
}
