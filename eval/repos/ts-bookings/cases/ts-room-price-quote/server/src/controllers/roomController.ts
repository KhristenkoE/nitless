import type { Request, Response } from 'express';
import { sendResult } from '../lib/http.js';
import { actorOf } from '../middleware/auth.js';
import type {
  AvailabilityQuery,
  ListRoomsQuery,
  QuoteQuery,
  UpdateRoomInput,
} from '../schemas/room.js';
import * as availabilityService from '../services/availabilityService.js';
import * as quoteService from '../services/quoteService.js';
import * as roomService from '../services/roomService.js';

export async function list(_req: Request, res: Response): Promise<void> {
  sendResult(res, await roomService.listRooms(res.locals.query as ListRoomsQuery));
}

export async function get(req: Request<{ roomId: string }>, res: Response): Promise<void> {
  sendResult(res, await roomService.getRoom(req.params.roomId));
}

export async function availability(req: Request<{ roomId: string }>, res: Response): Promise<void> {
  const { day } = res.locals.query as AvailabilityQuery;
  sendResult(res, await availabilityService.getFreeSlots(req.params.roomId, day));
}

export async function quote(req: Request<{ roomId: string }>, res: Response): Promise<void> {
  const query = res.locals.query as QuoteQuery;
  sendResult(res, await quoteService.quoteBooking(req.params.roomId, query));
}

export async function update(req: Request<{ roomId: string }>, res: Response): Promise<void> {
  const patch = req.body as UpdateRoomInput;
  sendResult(res, await roomService.updateRoom(actorOf(req), req.params.roomId, patch));
}

export async function archive(req: Request<{ roomId: string }>, res: Response): Promise<void> {
  sendResult(res, await roomService.archiveRoom(actorOf(req), req.params.roomId));
}
