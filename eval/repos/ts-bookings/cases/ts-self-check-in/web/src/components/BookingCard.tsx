import { flags } from '../lib/flags';
import { formatDay, formatTimeRange, isCheckInOpen, isInFuture } from '../lib/format';
import type { Booking } from '../types';
import { CheckInButton } from './CheckInButton';

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
  const canCheckIn =
    flags.isEnabled('self-check-in') &&
    booking.status === 'confirmed' &&
    isCheckInOpen(booking.startsAt);

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
      {canCheckIn && <CheckInButton booking={booking} />}
      {onCancel && canCancel && (
        <button type="button" onClick={() => onCancel(booking)} disabled={cancelling}>
          {cancelling ? 'Cancelling…' : 'Cancel booking'}
        </button>
      )}
    </article>
  );
}
