import type { Booking } from '../domain/types.js';
import * as eventRepository from '../repositories/eventRepository.js';

/**
 * Notifications are written to the outbox table; the mailer worker delivers them.
 * Unlike audit events these are awaited: a booking without its confirmation is a bug.
 */
export async function bookingConfirmed(booking: Booking): Promise<void> {
  await eventRepository.enqueueOutbox('booking.confirmed', {
    bookingId: booking.id,
    userId: booking.userId,
    roomId: booking.roomId,
    startsAt: booking.startsAt,
  });
}
