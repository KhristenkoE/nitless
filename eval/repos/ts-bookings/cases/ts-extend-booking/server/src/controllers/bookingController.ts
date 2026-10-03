import type { Request, Response } from 'express';
import { sendResult } from '../lib/http.js';
import { actorOf } from '../middleware/auth.js';
import type { CreateBookingInput, ExtendBookingInput, RangeQuery } from '../schemas/booking.js';
import * as bookingService from '../services/bookingService.js';

export async function create(req: Request, res: Response): Promise<void> {
  const input = req.body as CreateBookingInput;
  sendResult(res, await bookingService.createBooking(actorOf(req), input), 201);
}

export async function cancel(req: Request<{ id: string }>, res: Response): Promise<void> {
  sendResult(res, await bookingService.cancelBooking(actorOf(req), req.params.id));
}

export async function checkIn(req: Request<{ id: string }>, res: Response): Promise<void> {
  sendResult(res, await bookingService.checkIn(actorOf(req), req.params.id));
}

export async function extend(req: Request<{ id: string }>, res: Response): Promise<void> {
  const { minutes } = req.body as ExtendBookingInput;
  const booking = await bookingService.extendBooking(actorOf(req), req.params.id, minutes);
  res.json({ data: booking });
}

export async function listMine(req: Request, res: Response): Promise<void> {
  const range = res.locals.query as RangeQuery;
  sendResult(res, await bookingService.listMyBookings(actorOf(req), range));
}

export async function listForRoom(req: Request<{ roomId: string }>, res: Response): Promise<void> {
  const range = res.locals.query as RangeQuery;
  sendResult(res, await bookingService.listRoomBookings(req.params.roomId, range));
}
