import type { Job } from "@/lib/api";
import { formatDate } from "@/lib/format";

/** Remaining-days badge for open jobs; red EXPIRED badge for closed ones. */
export default function StatusBadge({ job }: { job: Job }) {
  if (job.is_expired) {
    return (
      <span className="inline-flex items-center gap-1.5">
        <span className="rounded bg-red-600 px-2 py-0.5 text-xs font-bold tracking-wide text-white">
          EXPIRED
        </span>
        <span className="rounded bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">
          Expired on {formatDate(job.expired_on)}
        </span>
      </span>
    );
  }

  let text: string;
  let cls: string;
  if (job.days_left === null) {
    text = "Deadline not stated";
    cls = "bg-slate-100 text-slate-700";
  } else if (job.days_left === 0) {
    text = "Last day today";
    cls = "bg-red-100 text-red-800";
  } else if (job.closing_soon) {
    text = `Closing soon · ${job.days_left} day${job.days_left === 1 ? "" : "s"} left`;
    cls = "bg-amber-100 text-amber-900";
  } else {
    text = `${job.days_left} days left`;
    cls = "bg-emerald-100 text-emerald-800";
  }
  return <span className={`rounded px-2 py-0.5 text-xs font-semibold ${cls}`}>{text}</span>;
}
