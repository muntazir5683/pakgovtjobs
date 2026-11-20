"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/", label: "Available Jobs" },
  { href: "/expired-jobs", label: "Expired Jobs" },
];

export default function NavTabs() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex gap-1">
      {TABS.map((t) => {
        const active = t.href === "/" ? pathname === "/" : pathname.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={
              "rounded-md px-3 py-2 text-sm font-medium transition-colors " +
              (active
                ? "bg-emerald-700 text-white"
                : "text-slate-700 hover:bg-slate-100")
            }
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
