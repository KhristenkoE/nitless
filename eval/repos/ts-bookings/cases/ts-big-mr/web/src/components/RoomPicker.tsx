/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import { Link } from 'react-router-dom';
import { formatPrice } from '../lib/format';
import type { Room } from '../types';

interface Props {
  rooms: Room[];
}

export function RoomPicker({ rooms }: Props) {
  if (rooms.length === 0) {
    return <p className="empty">No rooms match.</p>;
  }

  return (
    <ul className="room-picker">
      {rooms.map((room) => (
        <li key={room.id}>
          <Link to={`/rooms/${room.id}`}>
            <strong>{room.name}</strong>
            <span>
              {room.capacity} seats · {formatPrice(room.hourlyRateCents, room.currency)}/h
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
