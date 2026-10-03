/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import type { Request, Response } from 'express';
import { vi } from 'vitest';

/** A Response double whose `status` and `json` are chainable mocks. */
export function mockResponse(): Response {
  const res = {
    locals: {},
    status: vi.fn().mockReturnThis(),
    json: vi.fn().mockReturnThis(),
  };
  return res as unknown as Response;
}

/** A Request double carrying only the given properties. */
export function mockRequest(props: Partial<Request> = {}): Request {
  return props as Request;
}
