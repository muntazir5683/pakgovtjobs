import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import StatusBadge from "@/components/StatusBadge";
import { fetchJob, type Job } from "@/lib/api";
import { formatDate, isPdf } from "@/lib/format";

export async function generateMetadata({ params }: PageProps<"/job/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const job = await fetchJob(slug).catch(() => null);
  if (!job) return { title: "Job not found" };
  return {
    title: job.title,
    description: `${job.title}${job.department ? ` — ${job.department}` : ""}. ${job.is_expired ? "Applications closed." : `Last date: ${job.last_date ? formatDate(job.last_date) : "see advertisement"}.`}`,
  };
}

export default function JobPage({ params }: PageProps<"/job/[slug]">) {
  return (
    <Suspense fallback={<div className="h-96 animate-pulse rounded-xl bg-slate-200/70" />}>
      <JobDetail params={params} />
    </Suspense>
  );
}

async function JobDetail({ params }: { params: PageProps<"/job/[slug]">["params"] }) {
  const { slug } = await params;
  const job = await fetchJob(slug);
  if (!job) notFound();

  return (
    <article className="mx-auto max-w-4xl">
      <Link
        href={job.is_expired ? "/expired-jobs" : "/"}
        className="text-sm text-emerald-800 hover:underline"
      >
        ← Back to {job.is_expired ? "expired" : "available"} jobs
      </Link>

      <header className="mt-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <StatusBadge job={job} />
        <h1 className="mt-3 text-2xl font-bold leading-snug text-slate-900">{job.title}</h1>
        {job.department && <p className="mt-1 text-slate-600">{job.department}</p>}

        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 text-sm sm:grid-cols-3">
          <Fact label="Sector" value={job.sector} />
          <Fact label="Province" value={job.province} />
          <Fact label="Total posts" value={job.total_posts != null ? String(job.total_posts) : "Not stated"} />
          <Fact label="Education" value={job.education ?? job.education_level ?? "Not stated"} />
          <Fact label="Posted" value={formatDate(job.publish_date)} />
          <Fact
            label="Last date to apply"
            value={job.last_date ? formatDate(job.last_date) : "Not stated in ad"}
            emphasize={job.is_expired}
          />
        </dl>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <ApplyButton job={job} />
          {job.ad_media_url && (
            <a
              href={job.ad_media_url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="rounded-md border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Open original advertisement ↗
            </a>
          )}
        </div>
        {job.is_expired && (
          <p className="mt-3 text-sm text-red-700">
            This vacancy closed on {formatDate(job.expired_on)}. Check the official website for any
            re-advertisement.
          </p>
        )}
      </header>

      {job.ad_media_url && <AdPreview url={job.ad_media_url} title={job.title} />}

      <p className="mt-6 text-xs text-slate-500">
        Source: {job.source ? `${job.source.name} (${job.source.url})` : "official website"}. Details were extracted
        automatically — always confirm them against the official advertisement.
      </p>
    </article>
  );
}

function Fact({ label, value, emphasize }: { label: string; value: string; emphasize?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className={`mt-0.5 font-medium ${emphasize ? "text-red-700" : "text-slate-900"}`}>{value}</dd>
    </div>
  );
}

function ApplyButton({ job }: { job: Job }) {
  if (job.is_expired) {
    return (
      <button
        type="button"
        disabled
        aria-disabled="true"
        title="Applications for this job are closed"
        className="cursor-not-allowed rounded-md bg-slate-200 px-5 py-2.5 text-sm font-semibold text-slate-500"
      >
        Apply on Official Website (closed)
      </button>
    );
  }
  return (
    <a
      href={job.official_apply_url}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="rounded-md bg-emerald-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-emerald-800"
    >
      Apply on Official Website ↗
    </a>
  );
}

function AdPreview({ url, title }: { url: string; title: string }) {
  return (
    <section className="mt-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold">Official advertisement</h2>
      {isPdf(url) ? (
        <iframe
          src={url}
          title={`Advertisement: ${title}`}
          className="h-[75vh] w-full rounded-md border border-slate-200"
          referrerPolicy="no-referrer"
        />
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- remote gov-site images, arbitrary hosts
        <img
          src={url}
          alt={`Advertisement: ${title}`}
          referrerPolicy="no-referrer"
          className="mx-auto max-h-[80vh] w-auto max-w-full rounded-md border border-slate-200"
        />
      )}
      <p className="mt-2 text-xs text-slate-500">
        If the preview is blank the official site may block embedding —{" "}
        <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="text-emerald-800 underline">
          open the advertisement directly
        </a>
        .
      </p>
    </section>
  );
}
