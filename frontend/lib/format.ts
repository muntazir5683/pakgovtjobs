/** Dates from the API are plain PKT calendar days (YYYY-MM-DD); format them without timezone shifts. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(d);
}

export function isPdf(url: string): boolean {
  return /\.pdf(\?|#|$)/i.test(url);
}
