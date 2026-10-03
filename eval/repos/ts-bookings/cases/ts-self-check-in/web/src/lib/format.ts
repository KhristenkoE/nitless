const timeFormat = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'UTC',
});

const dayFormat = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  timeZone: 'UTC',
});

export function formatTime(iso: string): string {
  return timeFormat.format(new Date(iso));
}

export function formatDay(iso: string): string {
  return dayFormat.format(new Date(iso));
}

export function formatTimeRange(startIso: string, endIso: string): string {
  return `${formatTime(startIso)}–${formatTime(endIso)}`;
}

export function formatPrice(cents: number, currency: string): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(cents / 100);
}

/** "YYYY-MM-DD" of the UTC day an ISO instant falls on; used as the API `day` parameter. */
export function toDayParam(iso: string): string {
  return iso.slice(0, 10);
}

/** Mirrors the server rule: check-in opens 10 minutes before the start and closes 15 minutes after. */
export function isCheckInOpen(startIso: string, now: Date = new Date()): boolean {
  const start = new Date(startIso).getTime();
  return now.getTime() >= start - 10 * 60_000 && now.getTime() < start + 15 * 60_000;
}

export function isInFuture(iso: string, now: Date = new Date()): boolean {
  return new Date(iso).getTime() > now.getTime();
}
