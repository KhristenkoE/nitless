import { z } from 'zod';
import { isBefore } from '../lib/time.js';

export const instant = z.string().datetime({ message: 'Expected a UTC ISO-8601 timestamp' });

export const createBookingBody = z
  .object({
    roomId: z.string().uuid(),
    title: z.string().trim().min(1).max(120),
    startsAt: instant,
    endsAt: instant,
  })
  .refine((body) => isBefore(body.startsAt, body.endsAt), {
    message: 'endsAt must be after startsAt',
    path: ['endsAt'],
  });

export type CreateBookingInput = z.infer<typeof createBookingBody>;

export const rangeQuery = z.object({
  from: instant.optional(),
  to: instant.optional(),
});

export type RangeQuery = z.infer<typeof rangeQuery>;

export const roomBookingsQuery = rangeQuery.extend({
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(1).max(200).default(50),
});

export type RoomBookingsQuery = z.infer<typeof roomBookingsQuery>;
