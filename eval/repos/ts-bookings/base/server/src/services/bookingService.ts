import { SLOT_MINUTES, type Actor, type Booking } from '../domain/types.js';
import * as audit from '../lib/audit.js';
import { conflict, forbidden, notFound, unprocessable } from '../lib/errors.js';
import { logger } from '../lib/logger.js';
import * as notifier from '../lib/notifier.js';
import { err, ok, type Result } from '../lib/result.js';
import { addMinutes, isBefore, isOnSlotBoundary, minutesBetween, now } from '../lib/time.js';
import * as bookingRepository from '../repositories/bookingRepository.js';
import * as roomRepository from '../repositories/roomRepository.js';
import type { CreateBookingInput, RangeQuery } from '../schemas/booking.js';

const log = logger.child({ module: 'bookingService' });

/** Check-in opens this many minutes before the start and closes this many after it. */
const CHECK_IN_EARLY_MINUTES = 10;
const CHECK_IN_LATE_MINUTES = 15;

const DEFAULT_SCHEDULE_DAYS = 7;

function canManage(actor: Actor, booking: Booking): boolean {
  return booking.userId === actor.id || actor.role === 'staff' || actor.role === 'admin';
}

export async function createBooking(
  actor: Actor,
  input: CreateBookingInput,
): Promise<Result<Booking>> {
  const room = await roomRepository.findById(input.roomId);
  if (!room || !room.active) return err(notFound('Room'));

  if (!isBefore(now(), input.startsAt)) {
    return err(unprocessable('Bookings must start in the future'));
  }
  if (!isOnSlotBoundary(input.startsAt, SLOT_MINUTES) || !isOnSlotBoundary(input.endsAt, SLOT_MINUTES)) {
    return err(unprocessable(`Bookings must align to ${SLOT_MINUTES}-minute slots`));
  }
  if (minutesBetween(input.startsAt, input.endsAt) > room.maxDurationMinutes) {
    return err(
      unprocessable(`${room.name} can be booked for at most ${room.maxDurationMinutes} minutes`, {
        reason: 'DURATION_EXCEEDED',
        maxDurationMinutes: room.maxDurationMinutes,
      }),
    );
  }

  const clashes = await bookingRepository.findOverlapping(room.id, input);
  if (clashes.length > 0) {
    return err(conflict('The room is already booked for part of that time'));
  }

  const booking = await bookingRepository.insert({ ...input, userId: actor.id });
  await notifier.bookingConfirmed(booking);
  void audit.record({ type: 'booking.created', actorId: actor.id, subjectId: booking.id });
  log.info({ bookingId: booking.id, roomId: room.id }, 'booking created');
  return ok(booking);
}

export async function cancelBooking(actor: Actor, id: string): Promise<Result<Booking>> {
  const booking = await bookingRepository.findById(id);
  if (!booking) return err(notFound('Booking'));
  if (!canManage(actor, booking)) return err(forbidden());
  if (booking.status === 'cancelled') return ok(booking);
  if (!isBefore(now(), booking.startsAt)) {
    return err(unprocessable('Bookings that have already started cannot be cancelled'));
  }

  const cancelled = await bookingRepository.markCancelled(id, now());
  if (!cancelled) return err(conflict('The booking was changed by someone else, please reload'));

  void audit.record({ type: 'booking.cancelled', actorId: actor.id, subjectId: id });
  log.info({ bookingId: id }, 'booking cancelled');
  return ok(cancelled);
}

export async function checkIn(actor: Actor, id: string): Promise<Result<Booking>> {
  const booking = await bookingRepository.findById(id);
  if (!booking) return err(notFound('Booking'));
  if (!canManage(actor, booking)) return err(forbidden());
  if (booking.status === 'checked_in') return ok(booking);
  if (booking.status === 'cancelled') return err(unprocessable('The booking was cancelled'));

  const at = now();
  const opensAt = addMinutes(booking.startsAt, -CHECK_IN_EARLY_MINUTES);
  const closesAt = addMinutes(booking.startsAt, CHECK_IN_LATE_MINUTES);
  if (isBefore(at, opensAt) || !isBefore(at, closesAt)) {
    return err(unprocessable('Check-in is not open for this booking'));
  }

  const checkedIn = await bookingRepository.markCheckedIn(id);
  if (!checkedIn) return err(conflict('The booking was changed by someone else, please reload'));

  void audit.record({ type: 'booking.checked_in', actorId: actor.id, subjectId: id });
  return ok(checkedIn);
}

export async function listMyBookings(actor: Actor, range: RangeQuery): Promise<Result<Booking[]>> {
  return ok(await bookingRepository.listForUser(actor.id, range));
}

export async function listRoomBookings(
  roomId: string,
  range: RangeQuery,
): Promise<Result<Booking[]>> {
  const room = await roomRepository.findById(roomId);
  if (!room) return err(notFound('Room'));

  const from = range.from ?? now();
  const to = range.to ?? addMinutes(from, DEFAULT_SCHEDULE_DAYS * 24 * 60);
  return ok(await bookingRepository.listForRoom(roomId, { from, to }));
}
