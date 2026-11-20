import Link from "next/link";
import type { Job } from "@/lib/api";
import { formatDate } from "@/lib/format";
import StatusBadge from "./StatusBadge";

export default function JobCard({ job }: { job: Job }) {
  return (
    <article
      className={
        "flex flex-col gap-3 rounded-xl border bg-white p-4 shadow-sm sm:p-5 " +
        (job.is_expired ? "border-red-200 bg-red-50/30" : "border-slate-200")
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusBadge job={job} />
        <span className="text-xs text-slate-500">Posted {formatDate(job.publish_date)}</span>
      </div>

      <div>
        <h2 className="text-lg font-semibold leading-snug text-slate-900">
          <Link href={`/job/${job.slug}`} className="hover:text-emerald-800 hover:underline">
            {job.title}
          </Link>
        </h2>
        {job.department && <p className="mt-0.5 text-sm text-slate-600">{job.department}</p>}
      </div>

      <div className="flex flex-wrap gap-1.5 text-xs">
        <span className="rounded-full bg-emerald-50 px-2.5 py-1 font-medium text-emerald-800">
          {job.sector}
        </span>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">{job.province}</span>
        {job.education_level && (
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">
            {job.education_level}
          </span>
        )}
        {job.total_posts != null && (
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">
            {job.total_posts} post{job.total_posts === 1 ? "" : "s"}
          </span>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <div>
          <dt className="text-xs text-slate-500">Last date</dt>
          <dd className="font-medium text-slate-900">
            {job.last_date ? formatDate(job.last_date) : "Not stated in ad"}
          </dd>
        </div>
        {job.education && (
          <div className="min-w-0">
            <dt className="text-xs text-slate-500">Education</dt>
            <dd className="truncate text-slate-900" title={job.education}>
              {job.education}
            </dd>
          </div>
        )}
      </dl>

      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        {job.is_expired ? (
          <span
            aria-disabled="true"
            className="cursor-not-allowed rounded-md bg-slate-200 px-3 py-2 text-sm font-medium text-slate-500"
          >
            Applications closed
          </span>
        ) : (
          <a
            href={job.official_apply_url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="rounded-md bg-emerald-700 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-800"
          >
            Apply on Official Website ↗
          </a>
        )}
        <Link
          href={`/job/${job.slug}`}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          View details
        </Link>
      </div>
    </article>
  );
}
