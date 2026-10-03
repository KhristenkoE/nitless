import type { Room } from '../domain/types.js';
import { emptySql, query, queryOne, sql } from '../lib/db.js';

interface RoomRow {
  id: string;
  name: string;
  capacity: number;
  hourly_rate_cents: number;
  currency: string;
  max_duration_minutes: number;
  active: boolean;
}

const COLUMNS = sql`id, name, capacity, hourly_rate_cents, currency, max_duration_minutes, active`;

function toRoom(row: RoomRow): Room {
  return {
    id: row.id,
    name: row.name,
    capacity: row.capacity,
    hourlyRateCents: row.hourly_rate_cents,
    currency: row.currency,
    maxDurationMinutes: row.max_duration_minutes,
    active: row.active,
  };
}

export interface RoomFilters {
  q?: string;
}

export async function list(filters: RoomFilters): Promise<Room[]> {
  const rows = await query<RoomRow>(sql`
    SELECT ${COLUMNS} FROM rooms
    WHERE active
      ${filters.q ? sql`AND name ILIKE ${`%${filters.q}%`}` : emptySql}
    ORDER BY name`);
  return rows.map(toRoom);
}

export async function findById(id: string): Promise<Room | undefined> {
  const row = await queryOne<RoomRow>(sql`SELECT ${COLUMNS} FROM rooms WHERE id = ${id}`);
  return row && toRoom(row);
}

export interface RoomPatch {
  name?: string;
  capacity?: number;
  hourlyRateCents?: number;
  maxDurationMinutes?: number;
  active?: boolean;
}

export async function update(id: string, patch: RoomPatch): Promise<Room | undefined> {
  const row = await queryOne<RoomRow>(sql`
    UPDATE rooms SET
      name = COALESCE(${patch.name ?? null}, name),
      capacity = COALESCE(${patch.capacity ?? null}, capacity),
      hourly_rate_cents = COALESCE(${patch.hourlyRateCents ?? null}, hourly_rate_cents),
      max_duration_minutes = COALESCE(${patch.maxDurationMinutes ?? null}, max_duration_minutes),
      active = COALESCE(${patch.active ?? null}, active)
    WHERE id = ${id}
    RETURNING ${COLUMNS}`);
  return row && toRoom(row);
}
