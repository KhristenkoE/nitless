import type { Actor, Room } from '../domain/types.js';
import { notFound } from '../lib/errors.js';
import { logger } from '../lib/logger.js';
import { err, ok, type Result } from '../lib/result.js';
import { END_OF_TIME, now } from '../lib/time.js';
import * as bookingRepository from '../repositories/bookingRepository.js';
import * as roomRepository from '../repositories/roomRepository.js';
import type { ListRoomsQuery, UpdateRoomInput } from '../schemas/room.js';

const log = logger.child({ module: 'roomService' });

export async function listRooms(filters: ListRoomsQuery): Promise<Result<Room[]>> {
  return ok(await roomRepository.list(filters));
}

export async function getRoom(id: string): Promise<Result<Room>> {
  const room = await roomRepository.findById(id);
  return room ? ok(room) : err(notFound('Room'));
}

export async function updateRoom(
  actor: Actor,
  id: string,
  patch: UpdateRoomInput,
): Promise<Result<Room>> {
  const updated = await roomRepository.update(id, patch);
  if (!updated) return err(notFound('Room'));
  log.info({ roomId: id, actorId: actor.id, fields: Object.keys(patch) }, 'room updated');
  return ok(updated);
}

/**
 * Deactivates a room and cancels every booking that has not ended yet, so that
 * nobody shows up to a room that is gone.
 */
export async function archiveRoom(actor: Actor, id: string): Promise<Result<Room>> {
  const room = await roomRepository.findById(id);
  if (!room) return err(notFound('Room'));
  if (!room.active) return ok(room);

  const at = now();
  const upcoming = await bookingRepository.listForRoom(id, { from: at, to: END_OF_TIME });
  for (const booking of upcoming) {
    await bookingRepository.markCancelled(booking.id, at);
  }

  const archived = await roomRepository.update(id, { active: false });
  if (!archived) return err(notFound('Room'));
  log.info({ roomId: id, actorId: actor.id, cancelled: upcoming.length }, 'room archived');
  return ok(archived);
}
