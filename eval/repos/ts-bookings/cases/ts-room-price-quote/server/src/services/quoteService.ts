import { SLOT_MINUTES } from '../domain/types.js';
import { notFound, unprocessable } from '../lib/errors.js';
import { err, ok, type Result } from '../lib/result.js';
import { isOnSlotBoundary, minutesBetween, utcDayOfWeek, type Instant } from '../lib/time.js';
import * as roomRepository from '../repositories/roomRepository.js';
import type { QuoteQuery } from '../schemas/room.js';

/** Bookings starting on a Saturday or Sunday (UTC) cost this much more. */
const WEEKEND_SURCHARGE = 0.25;

export interface Quote {
  roomId: string;
  startsAt: Instant;
  endsAt: Instant;
  minutes: number;
  totalCents: number;
  currency: string;
  weekendSurcharge: boolean;
}

function isWeekend(at: Instant): boolean {
  const day = utcDayOfWeek(at);
  return day === 0 || day === 6;
}

export async function quoteBooking(roomId: string, query: QuoteQuery): Promise<Result<Quote>> {
  const room = await roomRepository.findById(roomId);
  if (!room || !room.active) return err(notFound('Room'));

  if (!isOnSlotBoundary(query.startsAt, SLOT_MINUTES) || !isOnSlotBoundary(query.endsAt, SLOT_MINUTES)) {
    return err(unprocessable(`Quotes must align to ${SLOT_MINUTES}-minute slots`));
  }

  const minutes = minutesBetween(query.startsAt, query.endsAt);
  const baseCents = (minutes * room.hourlyRateCents) / 60;
  const weekendSurcharge = isWeekend(query.startsAt);
  const totalCents = Math.round(weekendSurcharge ? baseCents * (1 + WEEKEND_SURCHARGE) : baseCents);

  return ok({
    roomId: room.id,
    startsAt: query.startsAt,
    endsAt: query.endsAt,
    minutes,
    totalCents,
    currency: room.currency,
    weekendSurcharge,
  });
}
