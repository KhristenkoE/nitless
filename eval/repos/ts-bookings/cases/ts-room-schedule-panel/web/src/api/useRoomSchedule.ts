import { useQuery } from '@tanstack/react-query';
import type { Booking } from '../types';
import { apiClient } from './client';
import { queryKeys } from './queryKeys';

interface RoomBookingsResponse {
  data: Booking[];
}

/**
 * Staff view: all active bookings of a room from `from` for the next seven days
 * (the server's default window for /rooms/:roomId/bookings).
 */
export function useRoomSchedule(roomId: string, from: string) {
  return useQuery({
    queryKey: queryKeys.rooms.schedule(roomId, from),
    queryFn: async () => {
      const response = await apiClient.get<RoomBookingsResponse>(`/rooms/${roomId}/bookings`, {
        from,
      });
      return response.data;
    },
  });
}
