import { CLOSING_HOUR, OPENING_HOUR, SLOT_MINUTES, type Slot } from '../domain/types.js';
import { notFound } from '../lib/errors.js';
import { err, ok, type Result } from '../lib/result.js';
import { addMinutes, isBefore, now, utcDay } from '../lib/time.js';
import * as bookingRepository from '../repositories/bookingRepository.js';
import * as roomRepository from '../repositories/roomRepository.js';

/**
 * Free slots of a room on a UTC calendar day. Slots that already started are
 * omitted, so "today" only lists what can still be booked.
 */
export async function getFreeSlots(roomId: string, day: string): Promise<Result<Slot[]>> {
  const room = await roomRepository.findById(roomId);
  if (!room || !room.active) return err(notFound('Room'));

  const midnight = utcDay(day);
  const opensAt = addMinutes(midnight, OPENING_HOUR * 60);
  const closesAt = addMinutes(midnight, CLOSING_HOUR * 60);
  const booked = await bookingRepository.listForRoom(roomId, { from: opensAt, to: closesAt });
  const current = now();

  const slots: Slot[] = [];
  for (let start = opensAt; isBefore(start, closesAt); start = addMinutes(start, SLOT_MINUTES)) {
    const end = addMinutes(start, SLOT_MINUTES);
    if (isBefore(start, current)) continue;
    const taken = booked.some((b) => isBefore(b.startsAt, end) && isBefore(start, b.endsAt));
    if (!taken) slots.push({ startsAt: start, endsAt: end });
  }
  return ok(slots);
}
