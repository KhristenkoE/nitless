/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AppError, notFound, unprocessable, type ErrorCode } from '../src/lib/errors.js';
import { errorHandler, sendErrorResponse, sendResult } from '../src/lib/http.js';
import { err, ok } from '../src/lib/result.js';
import { mockRequest, mockResponse } from './support/express.js';

const log = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock('../src/lib/logger.js', () => ({ logger: { child: () => log } }));

describe('sendErrorResponse', () => {
  it.each<[ErrorCode, number]>([
    ['VALIDATION', 400],
    ['UNAUTHENTICATED', 401],
    ['FORBIDDEN', 403],
    ['NOT_FOUND', 404],
    ['CONFLICT', 409],
    ['UNPROCESSABLE', 422],
  ])('responds to %s with HTTP %i', (code, status) => {
    const res = mockResponse();
    sendErrorResponse(res, new AppError(code, 'Nope'));
    expect(res.status).toHaveBeenCalledWith(status);
    expect(res.json).toHaveBeenCalledWith({ error: { code, message: 'Nope', details: undefined } });
  });

  it('includes the error details in the envelope', () => {
    const res = mockResponse();
    sendErrorResponse(res, unprocessable('Too long', { reason: 'DURATION_EXCEEDED' }));
    expect(res.json).toHaveBeenCalledWith({
      error: {
        code: 'UNPROCESSABLE',
        message: 'Too long',
        details: { reason: 'DURATION_EXCEEDED' },
      },
    });
  });
});

describe('sendResult', () => {
  it('wraps a successful value in a data envelope', () => {
    const res = mockResponse();
    sendResult(res, ok({ id: 'room-1' }));
    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith({ data: { id: 'room-1' } });
  });

  it('uses the given status for successful results', () => {
    const res = mockResponse();
    sendResult(res, ok({ id: 'b-1' }), 201);
    expect(res.status).toHaveBeenCalledWith(201);
  });

  it("uses the error's status instead of the given one for failures", () => {
    const res = mockResponse();
    sendResult(res, err(notFound('Room')), 201);
    expect(res.status).toHaveBeenCalledWith(404);
    expect(res.json).toHaveBeenCalledWith({
      error: { code: 'NOT_FOUND', message: 'Room not found', details: undefined },
    });
  });
});

describe('errorHandler', () => {
  const req = mockRequest({ method: 'GET', path: '/rooms' });

  beforeEach(() => {
    log.error.mockClear();
  });

  it('sends thrown AppErrors as they are, without logging', () => {
    const res = mockResponse();
    errorHandler(notFound('Booking'), req, res, vi.fn());
    expect(res.status).toHaveBeenCalledWith(404);
    expect(log.error).not.toHaveBeenCalled();
  });

  it('logs unexpected errors and hides them behind a generic 500', () => {
    const res = mockResponse();
    const error = new Error('connection refused');
    errorHandler(error, req, res, vi.fn());
    expect(log.error).toHaveBeenCalledWith(
      { err: error, method: 'GET', path: '/rooms' },
      'unhandled error',
    );
    expect(res.status).toHaveBeenCalledWith(500);
    expect(res.json).toHaveBeenCalledWith({
      error: { code: 'INTERNAL', message: 'Something went wrong' },
    });
  });
});
