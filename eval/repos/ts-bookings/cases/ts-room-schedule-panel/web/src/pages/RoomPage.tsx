import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useRoom } from '../api/useRooms';
import { AvailabilityGrid } from '../components/AvailabilityGrid';
import { ErrorBanner } from '../components/ErrorBanner';
import { RoomSchedule } from '../components/RoomSchedule';
import { flags } from '../lib/flags';
import { formatPrice, toDayParam } from '../lib/format';

export function RoomPage() {
  const { roomId = '' } = useParams();
  const room = useRoom(roomId);
  const [day, setDay] = useState(() => toDayParam(new Date().toISOString()));

  if (room.isPending) return <p>Loading room…</p>;
  if (room.isError) return <ErrorBanner error={room.error} />;

  return (
    <section>
      <h2>{room.data.name}</h2>
      <p>
        {room.data.capacity} seats · {formatPrice(room.data.hourlyRateCents, room.data.currency)}/h ·
        up to {room.data.maxDurationMinutes / 60} h per booking
      </p>
      <label>
        Day
        <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
      </label>
      <AvailabilityGrid roomId={roomId} day={day} />
      {flags.isEnabled('room-schedule') && <RoomSchedule roomId={roomId} />}
    </section>
  );
}
