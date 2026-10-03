import { useCancelBooking, useMyBookings } from '../api/useBookings';
import { useRooms } from '../api/useRooms';
import { BookingList } from '../components/BookingList';
import { ErrorBanner } from '../components/ErrorBanner';

export function MyBookingsPage() {
  const bookings = useMyBookings();
  const rooms = useRooms();
  const cancel = useCancelBooking();

  return (
    <section>
      <h2>My bookings</h2>
      {bookings.isPending && <p>Loading bookings…</p>}
      <ErrorBanner error={bookings.error ?? cancel.error} />
      {bookings.data && (
        <BookingList
          bookings={bookings.data}
          rooms={rooms.data ?? []}
          onCancel={(booking) => cancel.mutate(booking.id)}
          cancellingId={cancel.isPending ? cancel.variables : undefined}
        />
      )}
    </section>
  );
}
