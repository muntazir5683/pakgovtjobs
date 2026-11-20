import { Suspense } from "react";
import JobsView, { ListSkeleton } from "@/components/JobsView";

export default function Home({ searchParams }: PageProps<"/">) {
  return (
    <>
      <h1 className="text-2xl font-bold text-slate-900 sm:text-3xl">Available Government Jobs</h1>
      <p className="mb-5 mt-1 text-sm text-slate-600">
        Open vacancies from official Pakistani sources. Every listing links to the official
        advertisement or application portal.
      </p>
      <Suspense fallback={<ListSkeleton />}>
        <JobsView status="active" basePath="/" searchParams={searchParams} />
      </Suspense>
    </>
  );
}
