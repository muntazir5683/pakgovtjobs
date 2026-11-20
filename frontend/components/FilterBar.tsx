"use client";

import Form from "next/form";
import Link from "next/link";
import { EDUCATION_LEVELS, PROVINCES, SECTORS } from "@/lib/taxonomy";

export type FilterValues = {
  q: string;
  sector: string;
  province: string;
  education: string;
};

function Select({
  name,
  label,
  value,
  options,
}: {
  name: string;
  label: string;
  value: string;
  options: string[];
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-slate-600">
      {label}
      <select
        name={name}
        defaultValue={value}
        onChange={(e) => e.currentTarget.form?.requestSubmit()}
        className="rounded-md border border-slate-300 bg-white px-2 py-2 text-sm text-slate-900"
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function FilterBar({
  action,
  values,
}: {
  action: string;
  values: FilterValues;
}) {
  const hasFilters = Object.values(values).some(Boolean);
  return (
    <Form
      action={action}
      className="grid gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr_auto]"
    >
      <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-slate-600 sm:col-span-2 lg:col-span-1">
        Search
        <input
          type="search"
          name="q"
          defaultValue={values.q}
          placeholder="Title, department, qualification…"
          className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400"
        />
      </label>
      <Select name="sector" label="Sector" value={values.sector} options={SECTORS} />
      <Select name="province" label="Province" value={values.province} options={PROVINCES} />
      <Select name="education" label="Education" value={values.education} options={EDUCATION_LEVELS} />
      <div className="flex items-end gap-2">
        <button
          type="submit"
          className="rounded-md bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800"
        >
          Search
        </button>
        {hasFilters && (
          <Link
            href={action}
            className="rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
          >
            Clear
          </Link>
        )}
      </div>
    </Form>
  );
}
