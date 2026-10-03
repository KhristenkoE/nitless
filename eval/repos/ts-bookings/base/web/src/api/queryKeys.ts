export interface RoomFilters {
  q?: string;
}

export const queryKeys = {
  rooms: {
    all: ['rooms'] as const,
    list: (filters: RoomFilters) => ['rooms', 'list', filters] as const,
    detail: (roomId: string) => ['rooms', 'detail', roomId] as const,
    availability: (roomId: string, day: string) => ['rooms', 'availability', roomId, day] as const,
  },
  bookings: {
    all: ['bookings'] as const,
    mine: () => ['bookings', 'mine'] as const,
  },
};
