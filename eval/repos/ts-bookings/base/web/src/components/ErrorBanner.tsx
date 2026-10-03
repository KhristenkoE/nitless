import { ApiError } from '../api/client';

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null;
  const message =
    error instanceof ApiError ? error.message : 'Something went wrong. Please try again.';
  return (
    <p role="alert" className="error-banner">
      {message}
    </p>
  );
}
