import { useState } from 'react';
import { ApiError } from '../api/client';
import { useRoomSchedule } from '../api/useRoomSchedule';
import { formatDay, formatTimeRange, toDayParam } from '../lib/format';
import { ErrorBanner } from './ErrorBanner';

interface Props {
  roomId: string;
}

/** Upcoming week of bookings for a room. Only staff and admins get data; others see nothing. */
export function RoomSchedule({ roomId }: Props) {
  const [from] = useState(() => `${toDayParam(new Date().toISOString())}T00:00:00.000Z`);
  const schedule = useRoomSchedule(roomId, from);

  if (schedule.error instanceof ApiError && schedule.error.status === 403) return null;
  if (schedule.isPending) return <p>Loading schedule…</p>;
  if (schedule.isError) return <ErrorBanner error={schedule.error} />;

  const bookings = schedule.data ?? [];

  return (
    <section className="room-schedule">
      <h3>This week</h3>
      {bookings.length === 0 ? (
        <p className="empty">No bookings in the next seven days.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Day</th>
              <th>Time</th>
              <th>Title</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {bookings.map((booking) => (
              <tr key={booking.id}>
                <td>{formatDay(booking.startsAt)}</td>
                <td>{formatTimeRange(booking.startsAt, booking.endsAt)}</td>
                <td>{booking.title}</td>
                <td>{booking.status === 'checked_in' ? 'Checked in' : 'Confirmed'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
