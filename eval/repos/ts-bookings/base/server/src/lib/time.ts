import { addMinutes as addMinutesTo, differenceInMinutes, isValid, parseISO } from 'date-fns';

/**
 * An instant in time as a UTC ISO-8601 string, e.g. "2026-03-02T09:30:00.000Z".
 * This is the only time representation used in the domain and on the wire.
 */
export type Instant = string;

export const END_OF_TIME: Instant = '9999-12-31T23:59:59.999Z';

function parse(at: Instant): Date {
  const date = parseISO(at);
  if (!isValid(date)) {
    throw new RangeError(`Invalid instant: ${at}`);
  }
  return date;
}

export function now(): Instant {
  return new Date().toISOString();
}

/** Normalises a Date (e.g. from pg) or an ISO string into an Instant. */
export function toInstant(value: Date | string): Instant {
  return (typeof value === 'string' ? parse(value) : value).toISOString();
}

export function addMinutes(at: Instant, minutes: number): Instant {
  return addMinutesTo(parse(at), minutes).toISOString();
}

/** Whole minutes from `start` to `end` (negative if `end` is earlier). */
export function minutesBetween(start: Instant, end: Instant): number {
  return differenceInMinutes(parse(end), parse(start));
}

export function isBefore(a: Instant, b: Instant): boolean {
  return parse(a).getTime() < parse(b).getTime();
}

export function isAfter(a: Instant, b: Instant): boolean {
  return parse(a).getTime() > parse(b).getTime();
}

/** Midnight UTC of the day `at` falls on. */
export function startOfUtcDay(at: Instant): Instant {
  const date = parse(at);
  return new Date(
    Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()),
  ).toISOString();
}

/** Parses a calendar day ("2026-03-02") into midnight UTC of that day. */
export function utcDay(day: string): Instant {
  return parse(`${day}T00:00:00.000Z`).toISOString();
}

/** 0 = Sunday ... 6 = Saturday, in UTC. */
export function utcDayOfWeek(at: Instant): number {
  return parse(at).getUTCDay();
}

export function isOnSlotBoundary(at: Instant, slotMinutes: number): boolean {
  const date = parse(at);
  return (
    date.getUTCSeconds() === 0 &&
    date.getUTCMilliseconds() === 0 &&
    date.getUTCMinutes() % slotMinutes === 0
  );
}
