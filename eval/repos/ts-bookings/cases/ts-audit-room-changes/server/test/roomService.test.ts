import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Booking, Room } from '../src/domain/types.js';
import * as audit from '../src/lib/audit.js';
import * as bookingRepository from '../src/repositories/bookingRepository.js';
import * as roomRepository from '../src/repositories/roomRepository.js';
import { archiveRoom, updateRoom } from '../src/services/roomService.js';

vi.mock('../src/repositories/bookingRepository.js');
vi.mock('../src/repositories/roomRepository.js');
vi.mock('../src/lib/audit.js', () => ({ record: vi.fn(() => Promise.resolve()) }));

const admin = { id: 'admin-1', role: 'admin' as const };

const room: Room = {
  id: 'room-1',
  name: 'Aurora',
  capacity: 8,
  hourlyRateCents: 2500,
  currency: 'EUR',
  maxDurationMinutes: 240,
  active: true,
};

const upcoming = { id: 'b-1', roomId: room.id } as Booking;

describe('room audit trail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(roomRepository.findById).mockResolvedValue(room);
    vi.mocked(roomRepository.update).mockImplementation(async (_id, patch) => ({ ...room, ...patch }));
    vi.mocked(bookingRepository.listForRoom).mockResolvedValue([upcoming]);
  });

  it('records which fields an update touched', async () => {
    await updateRoom(admin, room.id, { capacity: 10 });
    expect(audit.record).toHaveBeenCalledWith({
      type: 'room.updated',
      actorId: admin.id,
      subjectId: room.id,
      meta: { fields: ['capacity'] },
    });
  });

  it('records archiving together with the cancelled bookings', async () => {
    const result = await archiveRoom(admin, room.id);
    expect(result.ok).toBe(true);
    expect(audit.record).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'room.archived', meta: { cancelledBookingIds: ['b-1'] } }),
    );
  });

  it('does not record anything for unknown rooms', async () => {
    vi.mocked(roomRepository.update).mockResolvedValue(undefined);
    await updateRoom(admin, 'missing', { capacity: 10 });
    expect(audit.record).not.toHaveBeenCalled();
  });
});
