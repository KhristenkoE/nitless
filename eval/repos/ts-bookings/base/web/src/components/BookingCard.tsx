import { formatDay, formatTimeRange, isInFuture } from '../lib/format';
import type { Booking } from '../types';

interface Props {
  booking: Booking;
  roomName?: string;
  onCancel?: (booking: Booking) => void;
  cancelling?: boolean;
}

const STATUS_LABEL: Record<Booking['status'], string> = {
  confirmed: 'Confirmed',
  checked_in: 'Checked in',
  cancelled: 'Cancelled',
};

export function BookingCard({ booking, roomName, onCancel, cancelling = false }: Props) {
  const canCancel = booking.status === 'confirmed' && isInFuture(booking.startsAt);

  return (
    <article className={`booking-card booking-card--${booking.status}`}>
      <header>
        <h3>{booking.title}</h3>
        <span className="booking-card__status">{STATUS_LABEL[booking.status]}</span>
      </header>
      <p>
        {formatDay(booking.startsAt)} · {formatTimeRange(booking.startsAt, booking.endsAt)}
        {roomName && <> · {roomName}</>}
      </p>
      {onCancel && canCancel && (
        <button type="button" onClick={() => onCancel(booking)} disabled={cancelling}>
          {cancelling ? 'Cancelling…' : 'Cancel booking'}
        </button>
      )}
    </article>
  );
}
