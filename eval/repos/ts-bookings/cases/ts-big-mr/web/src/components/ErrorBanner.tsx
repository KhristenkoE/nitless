/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
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
