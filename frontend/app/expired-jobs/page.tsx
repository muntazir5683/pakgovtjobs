import type { Metadata } from "next";
import { Suspense } from "react";
import JobsView, { ListSkeleton } from "@/components/JobsView";

export const metadata: Metadata = { title: "Expired Jobs" };

export default function ExpiredJobs({ searchParams }: PageProps<"/expired-jobs">) {
  return (
    <>
      <h1 className="text-2xl font-bold text-slate-900 sm:text-3xl">Expired Jobs</h1>
      <p className="mb-5 mt-1 text-sm text-slate-600">
        Archive of closed vacancies, so you can check whether an older advertisement is still open.
        Applications for these jobs are closed.
      </p>
      <Suspense fallback={<ListSkeleton />}>
        <JobsView status="expired" basePath="/expired-jobs" searchParams={searchParams} />
      </Suspense>
    </>
  );
}
