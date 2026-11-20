import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import NavTabs from "@/components/NavTabs";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "PakGovJobs — Latest Government Jobs in Pakistan",
    template: "%s | PakGovJobs",
  },
  description:
    "Automatically updated government jobs from official Pakistani sources — federal, provincial, armed forces, police, medical and testing agencies. Every listing links to the official portal.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-slate-50 text-slate-900">
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 backdrop-blur">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
            <Link href="/" className="flex items-center gap-2 text-lg font-bold text-emerald-800">
              <span aria-hidden className="inline-block h-6 w-6 rounded bg-emerald-700" />
              PakGovJobs
            </Link>
            <Suspense fallback={<div className="h-9 w-64" />}>
              <NavTabs />
            </Suspense>
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>

        <footer className="border-t border-slate-200 bg-white">
          <div className="mx-auto max-w-6xl px-4 py-5 text-xs text-slate-500">
            PakGovJobs is an independent aggregator and is not affiliated with any government body.
            Listings are extracted automatically from official sources; always verify details on the
            official advertisement before applying. All dates are in Pakistan Standard Time (PKT).
          </div>
        </footer>
      </body>
    </html>
  );
}
