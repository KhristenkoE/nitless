import { useState } from 'react';
import { useRooms } from '../api/useRooms';
import { ErrorBanner } from '../components/ErrorBanner';
import { RoomPicker } from '../components/RoomPicker';
import { flags } from '../lib/flags';

const CAPACITY_OPTIONS = [2, 4, 8, 12, 20];

export function RoomsPage() {
  const [search, setSearch] = useState('');
  const [minCapacity, setMinCapacity] = useState<number | undefined>(undefined);
  const rooms = useRooms({ q: search.trim() || undefined, minCapacity });

  return (
    <section>
      <h2>Rooms</h2>
      {flags.isEnabled('room-search') && (
        <input
          type="search"
          placeholder="Search rooms"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      )}
      <label>
        Seats
        <select
          value={minCapacity ?? ''}
          onChange={(e) => setMinCapacity(e.target.value ? Number(e.target.value) : undefined)}
        >
          <option value="">Any size</option>
          {CAPACITY_OPTIONS.map((seats) => (
            <option key={seats} value={seats}>
              {seats}+ seats
            </option>
          ))}
        </select>
      </label>
      {rooms.isPending && <p>Loading rooms…</p>}
      <ErrorBanner error={rooms.error} />
      {rooms.data && <RoomPicker rooms={rooms.data} />}
    </section>
  );
}
