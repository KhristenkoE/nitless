/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import type { Instant } from '../lib/time.js';

/** Bookings are made in fixed slots of this length. */
export const SLOT_MINUTES = 30;

/** Opening hours, UTC. */
export const OPENING_HOUR = 8;
export const CLOSING_HOUR = 20;

export type Role = 'member' | 'staff' | 'admin';

export interface Actor {
  id: string;
  role: Role;
}

export interface Room {
  id: string;
  name: string;
  capacity: number;
  hourlyRateCents: number;
  currency: string;
  maxDurationMinutes: number;
  active: boolean;
}

export type BookingStatus = 'confirmed' | 'checked_in' | 'cancelled';

export interface Booking {
  id: string;
  roomId: string;
  userId: string;
  title: string;
  startsAt: Instant;
  endsAt: Instant;
  status: BookingStatus;
  createdAt: Instant;
  cancelledAt: Instant | null;
}

export interface Slot {
  startsAt: Instant;
  endsAt: Instant;
}

export interface Range {
  from: Instant;
  to: Instant;
}
