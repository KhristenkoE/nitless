import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { queryKeys } from '../api/queryKeys';
import type { Booking } from '../types';

interface Props {
  booking: Booking;
}

export function CheckInButton({ booking }: Props) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const checkIn = async () => {
    setPending(true);
    setError(null);
    try {
      const response = await fetch(`/api/bookings/${booking.id}/check-in`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => undefined)) as
          | { error?: { message?: string } }
          | undefined;
        setError(body?.error?.message ?? 'Check-in failed, please try again');
        return;
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.bookings.all });
    } catch {
      setError('Check-in failed, please try again');
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="check-in">
      <button type="button" onClick={checkIn} disabled={pending}>
        {pending ? 'Checking in…' : "I'm here — check in"}
      </button>
      {error && (
        <p role="alert" className="error-banner">
          {error}
        </p>
      )}
    </div>
  );
}
