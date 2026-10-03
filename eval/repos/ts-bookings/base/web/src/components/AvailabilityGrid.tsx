import { useState } from 'react';
import { useCreateBooking } from '../api/useBookings';
import { useAvailability } from '../api/useRooms';
import { formatTime } from '../lib/format';
import type { Slot } from '../types';
import { ErrorBanner } from './ErrorBanner';

interface Props {
  roomId: string;
  day: string;
}

export function AvailabilityGrid({ roomId, day }: Props) {
  const availability = useAvailability(roomId, day);
  const createBooking = useCreateBooking();
  const [selected, setSelected] = useState<Slot | null>(null);
  const [title, setTitle] = useState('');

  if (availability.isPending) return <p>Loading availability…</p>;
  if (availability.isError) return <ErrorBanner error={availability.error} />;

  const slots = availability.data;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    createBooking.mutate(
      { roomId, title: title.trim(), startsAt: selected.startsAt, endsAt: selected.endsAt },
      {
        onSuccess: () => {
          setSelected(null);
          setTitle('');
        },
      },
    );
  };

  return (
    <section className="availability">
      {slots.length === 0 ? (
        <p className="empty">No free slots on this day.</p>
      ) : (
        <div className="availability__slots">
          {slots.map((slot) => (
            <button
              key={slot.startsAt}
              type="button"
              aria-pressed={selected?.startsAt === slot.startsAt}
              onClick={() => setSelected(slot)}
            >
              {formatTime(slot.startsAt)}
            </button>
          ))}
        </div>
      )}

      {selected && (
        <form onSubmit={submit} className="availability__form">
          <label>
            Title
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} required />
          </label>
          <button type="submit" disabled={createBooking.isPending || title.trim() === ''}>
            Book {formatTime(selected.startsAt)}
          </button>
        </form>
      )}
      <ErrorBanner error={createBooking.error} />
    </section>
  );
}
