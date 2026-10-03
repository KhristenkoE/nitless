/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
/** Mirrors the API payloads (see server/src/domain/types.ts). Times are UTC ISO strings. */

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
  startsAt: string;
  endsAt: string;
  status: BookingStatus;
  createdAt: string;
  cancelledAt: string | null;
}

export interface Slot {
  startsAt: string;
  endsAt: string;
}
