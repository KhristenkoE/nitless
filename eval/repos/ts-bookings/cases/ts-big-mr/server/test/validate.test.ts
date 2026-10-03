/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import { describe, expect, it, vi } from 'vitest';
import { z } from 'zod';
import { validateBody, validateQuery } from '../src/middleware/validate.js';
import { mockRequest, mockResponse } from './support/express.js';

describe('validateBody', () => {
  const middleware = validateBody(z.object({ title: z.string().trim().min(1) }));

  it('replaces the body with the parsed value and continues', () => {
    const req = mockRequest({ body: { title: '  Planning  ', unknown: true } });
    const res = mockResponse();
    const next = vi.fn();

    middleware(req, res, next);

    expect(req.body).toEqual({ title: 'Planning' });
    expect(next).toHaveBeenCalledOnce();
    expect(res.status).not.toHaveBeenCalled();
  });

  it.each([
    [
      'a field is invalid',
      { title: '   ' },
      { formErrors: [], fieldErrors: { title: [expect.any(String)] } },
    ],
    ['the body is missing', undefined, { formErrors: [expect.any(String)], fieldErrors: {} }],
  ])('responds with 400 when %s', (_case, body, details) => {
    const req = mockRequest({ body });
    const res = mockResponse();
    const next = vi.fn();

    middleware(req, res, next);

    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith({
      error: { code: 'VALIDATION', message: 'Invalid request body', details },
    });
    expect(next).not.toHaveBeenCalled();
  });
});

describe('validateQuery', () => {
  const middleware = validateQuery(
    z.object({ page: z.coerce.number().int().positive().default(1) }),
  );

  it.each([
    [{}, { page: 1 }],
    [{ page: '3' }, { page: 3 }],
  ])('stores the parsed query %o in res.locals as %o', (query, parsed) => {
    const req = mockRequest({ query });
    const res = mockResponse();
    const next = vi.fn();

    middleware(req, res, next);

    expect(res.locals.query).toEqual(parsed);
    expect(next).toHaveBeenCalledOnce();
  });

  it('responds with 400 for an invalid query string', () => {
    const req = mockRequest({ query: { page: 'first' } });
    const res = mockResponse();
    const next = vi.fn();

    middleware(req, res, next);

    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith({
      error: {
        code: 'VALIDATION',
        message: 'Invalid query string',
        details: { formErrors: [], fieldErrors: { page: [expect.any(String)] } },
      },
    });
    expect(res.locals.query).toBeUndefined();
    expect(next).not.toHaveBeenCalled();
  });
});
