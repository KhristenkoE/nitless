/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import { useQuery } from '@tanstack/react-query';
import type { Room, Slot } from '../types';
import { apiClient } from './client';
import { queryKeys, type RoomFilters } from './queryKeys';

export function useRooms(filters: RoomFilters = {}) {
  return useQuery({
    queryKey: queryKeys.rooms.list(filters),
    queryFn: () => apiClient.get<Room[]>('/rooms', { q: filters.q }),
  });
}

export function useRoom(roomId: string) {
  return useQuery({
    queryKey: queryKeys.rooms.detail(roomId),
    queryFn: () => apiClient.get<Room>(`/rooms/${roomId}`),
  });
}

export function useAvailability(roomId: string, day: string) {
  return useQuery({
    queryKey: queryKeys.rooms.availability(roomId, day),
    queryFn: () => apiClient.get<Slot[]>(`/rooms/${roomId}/availability`, { day }),
  });
}
