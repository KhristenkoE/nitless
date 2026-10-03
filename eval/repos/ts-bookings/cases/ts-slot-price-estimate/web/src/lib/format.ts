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

/** Price of a time range at a flat hourly rate, rounded to whole minor units. */
export function estimatePriceCents(hourlyRateCents: number, startIso: string, endIso: string): number {
  const minutes = (new Date(endIso).getTime() - new Date(startIso).getTime()) / 60_000;
  return Math.round((hourlyRateCents * minutes) / 60);
}

/** "YYYY-MM-DD" of the UTC day an ISO instant falls on; used as the API `day` parameter. */
export function toDayParam(iso: string): string {
  return iso.slice(0, 10);
}

export function isInFuture(iso: string, now: Date = new Date()): boolean {
  return new Date(iso).getTime() > now.getTime();
}
