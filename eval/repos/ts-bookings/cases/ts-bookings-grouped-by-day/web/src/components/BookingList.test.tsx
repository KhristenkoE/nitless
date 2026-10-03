import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Booking } from '../types';
import { BookingList, groupByDay } from './BookingList';

function booking(id: string, startsAt: string): Booking {
  return {
    id,
    roomId: 'room-1',
    userId: 'u-1',
    title: `Meeting ${id}`,
    startsAt,
    endsAt: startsAt.replace(':00:00', ':30:00'),
    status: 'confirmed',
    createdAt: '2026-03-01T00:00:00.000Z',
    cancelledAt: null,
  };
}

const bookings = [
  booking('a', '2026-03-02T09:00:00.000Z'),
  booking('b', '2026-03-02T14:00:00.000Z'),
  booking('c', '2026-03-04T10:00:00.000Z'),
];

describe('groupByDay', () => {
  it('groups bookings by UTC start day in order', () => {
    expect(groupByDay(bookings).map((g) => [g.day, g.bookings.map((b) => b.id)])).toEqual([
      ['2026-03-02', ['a', 'b']],
      ['2026-03-04', ['c']],
    ]);
  });
});

describe('BookingList', () => {
  it('renders one section per day', () => {
    const { container } = render(
      <BookingList bookings={bookings} rooms={[]} onCancel={() => undefined} />,
    );
    expect(container.querySelectorAll('section.booking-list__day')).toHaveLength(2);
    expect(screen.getByText('Meeting c')).toBeTruthy();
  });

  it('shows an empty state', () => {
    render(<BookingList bookings={[]} rooms={[]} onCancel={() => undefined} />);
    expect(screen.getByText('You have no bookings yet.')).toBeTruthy();
  });
});
