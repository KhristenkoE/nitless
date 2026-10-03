import { Router } from 'express';
import * as bookingController from './controllers/bookingController.js';
import * as roomController from './controllers/roomController.js';
import { requireAuth, requireRole } from './middleware/auth.js';
import { validateBody, validateQuery } from './middleware/validate.js';
import { createBookingBody, rangeQuery } from './schemas/booking.js';
import { availabilityQuery, listRoomsQuery, updateRoomBody } from './schemas/room.js';

export const router = Router();

router.use(requireAuth);

// Rooms
router.get('/rooms', validateQuery(listRoomsQuery), roomController.list);
router.get('/rooms/:roomId', roomController.get);
router.get('/rooms/:roomId/availability', validateQuery(availabilityQuery), roomController.availability);
router.patch('/rooms/:roomId', requireRole('admin'), validateBody(updateRoomBody), roomController.update);
router.post('/rooms/:roomId/archive', requireRole('admin'), roomController.archive);
router.get(
  '/rooms/:roomId/bookings',
  requireRole('staff', 'admin'),
  validateQuery(rangeQuery),
  bookingController.listForRoom,
);

// Bookings
router.get('/bookings/mine', validateQuery(rangeQuery), bookingController.listMine);
router.post('/bookings', validateBody(createBookingBody), bookingController.create);
router.post('/bookings/:id/cancel', bookingController.cancel);
router.post('/bookings/:id/check-in', bookingController.checkIn);
