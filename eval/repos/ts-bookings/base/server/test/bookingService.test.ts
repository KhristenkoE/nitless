import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Booking, Room } from '../src/domain/types.js';
import * as bookingRepository from '../src/repositories/bookingRepository.js';
import * as roomRepository from '../src/repositories/roomRepository.js';
import { cancelBooking, createBooking } from '../src/services/bookingService.js';

vi.mock('../src/repositories/bookingRepository.js');
vi.mock('../src/repositories/roomRepository.js');
vi.mock('../src/lib/notifier.js');
vi.mock('../src/lib/audit.js', () => ({ record: vi.fn(() => Promise.resolve()) }));
vi.mock('../src/lib/time.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/lib/time.js')>()),
  now: () => '2026-03-02T08:00:00.000Z',
}));

const room: Room = {
  id: 'room-1',
  name: 'Aurora',
  capacity: 8,
  hourlyRateCents: 2500,
  currency: 'EUR',
  maxDurationMinutes: 120,
  active: true,
};

const booking: Booking = {
  id: 'b-1',
  roomId: room.id,
  userId: 'u-1',
  title: 'Planning',
  startsAt: '2026-03-02T09:00:00.000Z',
  endsAt: '2026-03-02T10:00:00.000Z',
  status: 'confirmed',
  createdAt: '2026-03-01T12:00:00.000Z',
  cancelledAt: null,
};

const member = { id: 'u-1', role: 'member' as const };

describe('createBooking', () => {
  beforeEach(() => {
    vi.mocked(roomRepository.findById).mockResolvedValue(room);
    vi.mocked(bookingRepository.findOverlapping).mockResolvedValue([]);
    vi.mocked(bookingRepository.insert).mockResolvedValue(booking);
  });

  const input = {
    roomId: room.id,
    title: 'Planning',
    startsAt: '2026-03-02T09:00:00.000Z',
    endsAt: '2026-03-02T10:00:00.000Z',
  };

  it('creates a booking in a free slot', async () => {
    const result = await createBooking(member, input);
    expect(result).toEqual({ ok: true, value: booking });
  });

  it('rejects overlapping bookings', async () => {
    vi.mocked(bookingRepository.findOverlapping).mockResolvedValue([booking]);
    const result = await createBooking(member, input);
    expect(result.ok).toBe(false);
    expect(!result.ok && result.error.code).toBe('CONFLICT');
  });

  it('enforces the room duration limit', async () => {
    const result = await createBooking(member, { ...input, endsAt: '2026-03-02T12:00:00.000Z' });
    expect(!result.ok && result.error.details).toMatchObject({ reason: 'DURATION_EXCEEDED' });
  });

  it('rejects slots that are not aligned', async () => {
    const result = await createBooking(member, { ...input, startsAt: '2026-03-02T09:10:00.000Z' });
    expect(!result.ok && result.error.code).toBe('UNPROCESSABLE');
  });
});

describe('cancelBooking', () => {
  it('does not let members cancel bookings of others', async () => {
    vi.mocked(bookingRepository.findById).mockResolvedValue({ ...booking, userId: 'u-2' });
    const result = await cancelBooking(member, booking.id);
    expect(!result.ok && result.error.code).toBe('FORBIDDEN');
  });

  it('is idempotent for already cancelled bookings', async () => {
    const cancelled = { ...booking, status: 'cancelled' as const };
    vi.mocked(bookingRepository.findById).mockResolvedValue(cancelled);
    expect(await cancelBooking(member, booking.id)).toEqual({ ok: true, value: cancelled });
    expect(bookingRepository.markCancelled).not.toHaveBeenCalled();
  });
});
