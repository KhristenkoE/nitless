/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Booking, Room, Slot } from '../src/domain/types.js';
import type * as time from '../src/lib/time.js';
import { now } from '../src/lib/time.js';
import * as bookingRepository from '../src/repositories/bookingRepository.js';
import * as roomRepository from '../src/repositories/roomRepository.js';
import { getFreeSlots } from '../src/services/availabilityService.js';

vi.mock('../src/repositories/bookingRepository.js');
vi.mock('../src/repositories/roomRepository.js');
vi.mock('../src/lib/time.js', async (importOriginal) => ({
  ...(await importOriginal<typeof time>()),
  now: vi.fn(),
}));

const DAY = '2026-03-02';

/** An instant on DAY, e.g. at('09:30') -> "2026-03-02T09:30:00.000Z". */
const at = (time: string) => `${DAY}T${time}:00.000Z`;

const room: Room = {
  id: 'room-1',
  name: 'Aurora',
  capacity: 8,
  hourlyRateCents: 2500,
  currency: 'EUR',
  maxDurationMinutes: 120,
  active: true,
};

function booked(id: string, from: string, to: string): Booking {
  return {
    id,
    roomId: room.id,
    userId: 'u-1',
    title: 'Planning',
    startsAt: at(from),
    endsAt: at(to),
    status: 'confirmed',
    createdAt: '2026-03-01T12:00:00.000Z',
    cancelledAt: null,
  };
}

async function freeSlots(): Promise<Slot[]> {
  const result = await getFreeSlots(room.id, DAY);
  if (!result.ok) throw result.error;
  return result.value;
}

/** Start times of the free slots as "HH:MM". */
async function freeStartTimes(): Promise<string[]> {
  return (await freeSlots()).map((slot) => slot.startsAt.slice(11, 16));
}

describe('getFreeSlots', () => {
  beforeEach(() => {
    vi.mocked(now).mockReturnValue(at('07:00'));
    vi.mocked(roomRepository.findById).mockResolvedValue(room);
    vi.mocked(bookingRepository.listForRoom).mockResolvedValue([]);
  });

  it.each([
    ['unknown', undefined],
    ['archived', { ...room, active: false }],
  ])('returns NOT_FOUND for an %s room', async (_case, found) => {
    vi.mocked(roomRepository.findById).mockResolvedValue(found);
    const result = await getFreeSlots(room.id, DAY);
    expect(!result.ok && result.error.code).toBe('NOT_FOUND');
    expect(bookingRepository.listForRoom).not.toHaveBeenCalled();
  });

  it('lists every 30-minute slot between opening and closing on a free day', async () => {
    const slots = await freeSlots();
    expect(bookingRepository.listForRoom).toHaveBeenCalledWith(room.id, {
      from: at('08:00'),
      to: at('20:00'),
    });
    expect(slots).toHaveLength(24);
    expect(slots[0]).toEqual({ startsAt: at('08:00'), endsAt: at('08:30') });
    expect(slots[23]).toEqual({ startsAt: at('19:30'), endsAt: at('20:00') });
  });

  it.each([
    ['12:00', '12:00', 16],
    ['12:10', '12:30', 15],
    ['19:30', '19:30', 1],
  ])('at %s omits started slots and starts at %s (%i left)', async (time, first, count) => {
    vi.mocked(now).mockReturnValue(at(time));
    const starts = await freeStartTimes();
    expect(starts[0]).toBe(first);
    expect(starts).toHaveLength(count);
  });

  it('returns no slots once the room has closed', async () => {
    vi.mocked(now).mockReturnValue(at('20:00'));
    expect(await freeSlots()).toEqual([]);
  });

  describe('late in the day', () => {
    // From 17:00 only six slots remain, which keeps the expected lists short.
    beforeEach(() => {
      vi.mocked(now).mockReturnValue(at('17:00'));
    });

    it.each([
      ['nothing is booked', [], ['17:00', '17:30', '18:00', '18:30', '19:00', '19:30']],
      [
        'an hour is booked',
        [booked('b-1', '18:00', '19:00')],
        ['17:00', '17:30', '19:00', '19:30'],
      ],
      [
        'back-to-back bookings cover the first hour',
        [booked('b-1', '17:00', '17:30'), booked('b-2', '17:30', '18:00')],
        ['18:00', '18:30', '19:00', '19:30'],
      ],
      [
        'a booking ends exactly when the first slot starts',
        [booked('b-1', '16:00', '17:00')],
        ['17:00', '17:30', '18:00', '18:30', '19:00', '19:30'],
      ],
    ])('returns the free slots when %s', async (_case, bookings, expected) => {
      vi.mocked(bookingRepository.listForRoom).mockResolvedValue(bookings);
      expect(await freeStartTimes()).toEqual(expected);
    });
  });
});
