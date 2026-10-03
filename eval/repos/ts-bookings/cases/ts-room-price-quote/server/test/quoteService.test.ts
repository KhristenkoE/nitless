import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Room } from '../src/domain/types.js';
import * as roomRepository from '../src/repositories/roomRepository.js';
import { quoteBooking } from '../src/services/quoteService.js';

vi.mock('../src/repositories/roomRepository.js');

const room: Room = {
  id: 'room-1',
  name: 'Aurora',
  capacity: 8,
  hourlyRateCents: 2500,
  currency: 'EUR',
  maxDurationMinutes: 240,
  active: true,
};

describe('quoteBooking', () => {
  beforeEach(() => {
    vi.mocked(roomRepository.findById).mockResolvedValue(room);
  });

  it('prices weekday bookings at the hourly rate', async () => {
    // Monday
    const result = await quoteBooking(room.id, {
      startsAt: '2026-03-02T09:00:00.000Z',
      endsAt: '2026-03-02T10:30:00.000Z',
    });
    expect(result).toEqual({
      ok: true,
      value: expect.objectContaining({ minutes: 90, totalCents: 3750, currency: 'EUR', weekendSurcharge: false }),
    });
  });

  it('adds the weekend surcharge', async () => {
    // Saturday
    const result = await quoteBooking(room.id, {
      startsAt: '2026-03-07T09:00:00.000Z',
      endsAt: '2026-03-07T10:00:00.000Z',
    });
    expect(result.ok && result.value.totalCents).toBe(3125);
  });

  it('rejects unaligned ranges', async () => {
    const result = await quoteBooking(room.id, {
      startsAt: '2026-03-02T09:15:00.000Z',
      endsAt: '2026-03-02T10:00:00.000Z',
    });
    expect(!result.ok && result.error.code).toBe('UNPROCESSABLE');
  });

  it('returns not found for archived rooms', async () => {
    vi.mocked(roomRepository.findById).mockResolvedValue({ ...room, active: false });
    const result = await quoteBooking(room.id, {
      startsAt: '2026-03-02T09:00:00.000Z',
      endsAt: '2026-03-02T10:00:00.000Z',
    });
    expect(!result.ok && result.error.code).toBe('NOT_FOUND');
  });
});
