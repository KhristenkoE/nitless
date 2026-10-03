import { z } from 'zod';

export const listRoomsQuery = z.object({
  q: z.string().trim().min(1).max(60).optional(),
  minCapacity: z.coerce.number().int().positive().max(500).optional(),
});

export type ListRoomsQuery = z.infer<typeof listRoomsQuery>;

export const updateRoomBody = z
  .object({
    name: z.string().trim().min(1).max(80),
    capacity: z.number().int().positive().max(500),
    hourlyRateCents: z.number().int().nonnegative(),
    maxDurationMinutes: z.number().int().positive().multipleOf(30).max(12 * 60),
  })
  .partial()
  .refine((body) => Object.keys(body).length > 0, { message: 'Nothing to update' });

export type UpdateRoomInput = z.infer<typeof updateRoomBody>;

export const availabilityQuery = z.object({
  day: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Expected YYYY-MM-DD'),
});

export type AvailabilityQuery = z.infer<typeof availabilityQuery>;
