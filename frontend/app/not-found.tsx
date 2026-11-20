import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md py-10 text-center">
      <h1 className="text-xl font-semibold">Job not found</h1>
      <p className="mt-1 text-sm text-slate-600">This listing doesn’t exist or the link is wrong.</p>
      <Link href="/" className="mt-4 inline-block text-emerald-800 underline">
        Browse available jobs
      </Link>
    </div>
  );
}
