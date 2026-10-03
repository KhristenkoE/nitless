/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import { useState } from 'react';
import { useRooms } from '../api/useRooms';
import { ErrorBanner } from '../components/ErrorBanner';
import { RoomPicker } from '../components/RoomPicker';
import { flags } from '../lib/flags';

export function RoomsPage() {
  const [search, setSearch] = useState('');
  const rooms = useRooms({ q: search.trim() || undefined });

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
      {rooms.isPending && <p>Loading rooms…</p>}
      <ErrorBanner error={rooms.error} />
      {rooms.data && <RoomPicker rooms={rooms.data} />}
    </section>
  );
}
