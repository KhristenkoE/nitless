import type { Booking, BookingStatus, Range, Slot } from '../domain/types.js';
import { emptySql, query, queryOne, sql } from '../lib/db.js';
import { toInstant, type Instant } from '../lib/time.js';

interface BookingRow {
  id: string;
  room_id: string;
  user_id: string;
  title: string;
  starts_at: Date;
  ends_at: Date;
  status: BookingStatus;
  created_at: Date;
  cancelled_at: Date | null;
}

const COLUMNS = sql`id, room_id, user_id, title, starts_at, ends_at, status, created_at, cancelled_at`;

function toBooking(row: BookingRow): Booking {
  return {
    id: row.id,
    roomId: row.room_id,
    userId: row.user_id,
    title: row.title,
    startsAt: toInstant(row.starts_at),
    endsAt: toInstant(row.ends_at),
    status: row.status,
    createdAt: toInstant(row.created_at),
    cancelledAt: row.cancelled_at ? toInstant(row.cancelled_at) : null,
  };
}

export async function findById(id: string): Promise<Booking | undefined> {
  const row = await queryOne<BookingRow>(sql`SELECT ${COLUMNS} FROM bookings WHERE id = ${id}`);
  return row && toBooking(row);
}

/** Active (not cancelled) bookings of a room that intersect `range`, oldest first. */
export async function listForRoom(roomId: string, range: Range): Promise<Booking[]> {
  const rows = await query<BookingRow>(sql`
    SELECT ${COLUMNS} FROM bookings
    WHERE room_id = ${roomId}
      AND status <> 'cancelled'
      AND starts_at < ${range.to}
      AND ends_at > ${range.from}
    ORDER BY starts_at`);
  return rows.map(toBooking);
}

export async function listForUser(userId: string, range: Partial<Range>): Promise<Booking[]> {
  const rows = await query<BookingRow>(sql`
    SELECT ${COLUMNS} FROM bookings
    WHERE user_id = ${userId}
      ${range.from ? sql`AND ends_at > ${range.from}` : emptySql}
      ${range.to ? sql`AND starts_at < ${range.to}` : emptySql}
    ORDER BY starts_at`);
  return rows.map(toBooking);
}

/** Active bookings of a room that share at least one instant with `slot`. */
export async function findOverlapping(roomId: string, slot: Slot): Promise<Booking[]> {
  const rows = await query<BookingRow>(sql`
    SELECT ${COLUMNS} FROM bookings
    WHERE room_id = ${roomId}
      AND status <> 'cancelled'
      AND starts_at < ${slot.endsAt}
      AND ends_at > ${slot.startsAt}`);
  return rows.map(toBooking);
}

export interface NewBooking {
  roomId: string;
  userId: string;
  title: string;
  startsAt: Instant;
  endsAt: Instant;
}

export async function insert(booking: NewBooking): Promise<Booking> {
  const row = await queryOne<BookingRow>(sql`
    INSERT INTO bookings (room_id, user_id, title, starts_at, ends_at)
    VALUES (${booking.roomId}, ${booking.userId}, ${booking.title}, ${booking.startsAt}, ${booking.endsAt})
    RETURNING ${COLUMNS}`);
  return toBooking(row!);
}

/** Returns undefined if the booking was already cancelled. */
export async function markCancelled(id: string, at: Instant): Promise<Booking | undefined> {
  const row = await queryOne<BookingRow>(sql`
    UPDATE bookings SET status = 'cancelled', cancelled_at = ${at}
    WHERE id = ${id} AND status <> 'cancelled'
    RETURNING ${COLUMNS}`);
  return row && toBooking(row);
}

/**
 * Moves the end of a booking. Guarded by the end we read, so two concurrent
 * extensions cannot both succeed. Returns undefined if the guard did not match.
 */
export async function updateEndsAt(
  id: string,
  expectedEndsAt: Instant,
  endsAt: Instant,
): Promise<Booking | undefined> {
  const row = await queryOne<BookingRow>(sql`
    UPDATE bookings SET ends_at = ${endsAt}
    WHERE id = ${id} AND ends_at = ${expectedEndsAt} AND status <> 'cancelled'
    RETURNING ${COLUMNS}`);
  return row && toBooking(row);
}

/** Returns undefined unless the booking was still `confirmed`. */
export async function markCheckedIn(id: string): Promise<Booking | undefined> {
  const row = await queryOne<BookingRow>(sql`
    UPDATE bookings SET status = 'checked_in'
    WHERE id = ${id} AND status = 'confirmed'
    RETURNING ${COLUMNS}`);
  return row && toBooking(row);
}
