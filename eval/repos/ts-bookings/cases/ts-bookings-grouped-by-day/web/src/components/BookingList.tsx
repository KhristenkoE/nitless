import { formatDay, toDayParam } from '../lib/format';
import type { Booking, Room } from '../types';
import { BookingCard } from './BookingCard';

interface Props {
  bookings: Booking[];
  rooms: Room[];
  onCancel: (booking: Booking) => void;
  cancellingId?: string;
}

interface DayGroup {
  day: string;
  bookings: Booking[];
}

/** Groups bookings by the UTC day they start on, keeping the incoming (chronological) order. */
export function groupByDay(bookings: Booking[]): DayGroup[] {
  const groups = new Map<string, Booking[]>();
  for (const booking of bookings) {
    const day = toDayParam(booking.startsAt);
    const group = groups.get(day);
    if (group) {
      group.push(booking);
    } else {
      groups.set(day, [booking]);
    }
  }
  return Array.from(groups, ([day, items]) => ({ day, bookings: items }));
}

export function BookingList({ bookings, rooms, onCancel, cancellingId }: Props) {
  if (bookings.length === 0) {
    return <p className="empty">You have no bookings yet.</p>;
  }

  const roomNames = new Map(rooms.map((room) => [room.id, room.name]));

  return (
    <div className="booking-list">
      {groupByDay(bookings).map((group, index) => (
        <section key={index} className="booking-list__day">
          <h3>{formatDay(`${group.day}T00:00:00.000Z`)}</h3>
          <ul>
            {group.bookings.map((booking) => (
              <li key={booking.id}>
                <BookingCard
                  booking={booking}
                  roomName={roomNames.get(booking.roomId)}
                  onCancel={onCancel}
                  cancelling={cancellingId === booking.id}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
