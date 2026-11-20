import Link from "next/link";

export default function Pagination({
  basePath,
  params,
  page,
  pages,
}: {
  basePath: string;
  params: Record<string, string>;
  page: number;
  pages: number;
}) {
  if (pages <= 1) return null;
  const href = (p: number) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v),
    );
    if (p > 1) qs.set("page", String(p));
    const s = qs.toString();
    return s ? `${basePath}?${s}` : basePath;
  };
  const btn = "rounded-md border border-slate-300 px-3 py-2 text-sm font-medium";
  return (
    <nav aria-label="Pagination" className="mt-6 flex items-center justify-between">
      {page > 1 ? (
        <Link href={href(page - 1)} className={`${btn} text-slate-700 hover:bg-slate-50`}>
          ← Previous
        </Link>
      ) : (
        <span className={`${btn} cursor-not-allowed text-slate-300`}>← Previous</span>
      )}
      <span className="text-sm text-slate-600">
        Page {page} of {pages}
      </span>
      {page < pages ? (
        <Link href={href(page + 1)} className={`${btn} text-slate-700 hover:bg-slate-50`}>
          Next →
        </Link>
      ) : (
        <span className={`${btn} cursor-not-allowed text-slate-300`}>Next →</span>
      )}
    </nav>
  );
}
