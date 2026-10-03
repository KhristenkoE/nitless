import type { Booking, Room } from '../types';
import { BookingCard } from './BookingCard';

interface Props {
  bookings: Booking[];
  rooms: Room[];
  onCancel: (booking: Booking) => void;
  cancellingId?: string;
}

export function BookingList({ bookings, rooms, onCancel, cancellingId }: Props) {
  if (bookings.length === 0) {
    return <p className="empty">You have no bookings yet.</p>;
  }

  const roomNames = new Map(rooms.map((room) => [room.id, room.name]));

  return (
    <ul className="booking-list">
      {bookings.map((booking) => (
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
  );
}
