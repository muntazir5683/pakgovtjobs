"use client";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="mx-auto max-w-md rounded-xl border border-red-200 bg-white p-6 text-center shadow-sm">
      <h1 className="text-lg font-semibold text-slate-900">Couldn’t load jobs</h1>
      <p className="mt-1 text-sm text-slate-600">
        The jobs service is unreachable right now. Please try again in a moment.
      </p>
      <button
        onClick={reset}
        className="mt-4 rounded-md bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800"
      >
        Retry
      </button>
    </div>
  );
}
