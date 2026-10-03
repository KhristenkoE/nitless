import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Booking } from '../types';
import { apiClient } from './client';
import { queryKeys } from './queryKeys';

export function useMyBookings() {
  return useQuery({
    queryKey: queryKeys.bookings.mine(),
    queryFn: () => apiClient.get<Booking[]>('/bookings/mine'),
  });
}

export interface NewBooking {
  roomId: string;
  title: string;
  startsAt: string;
  endsAt: string;
}

export function useCreateBooking() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: NewBooking) => apiClient.post<Booking>('/bookings', input),
    onSuccess: (booking) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.bookings.all });
      void queryClient.invalidateQueries({
        queryKey: ['rooms', 'availability', booking.roomId],
      });
    },
  });
}

export function useCancelBooking() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (bookingId: string) => apiClient.post<Booking>(`/bookings/${bookingId}/cancel`),
    onSuccess: (booking) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.bookings.all });
      void queryClient.invalidateQueries({
        queryKey: ['rooms', 'availability', booking.roomId],
      });
    },
  });
}
