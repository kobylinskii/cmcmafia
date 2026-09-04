const CLUB_TZ = "Europe/Moscow";

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: CLUB_TZ,
  }).format(new Date(iso));
}

export function formatDateLong(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: CLUB_TZ,
  }).format(new Date(iso));
}

export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: CLUB_TZ,
  }).format(new Date(iso));
}

/** Local "YYYY-MM-DDTHH:mm" for <input type="datetime-local">, in club time. */
export function toDatetimeLocalValue(iso: string): string {
  const parts = new Intl.DateTimeFormat("sv-SE", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: CLUB_TZ,
    hour12: false,
  }).formatToParts(new Date(iso));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 1000) / 10}%`;
}

export function formatDash(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return String(Math.round(value * 100) / 100);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value);
}
