/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import type { NextFunction, Request, Response } from 'express';
import { AppError } from './errors.js';
import { logger } from './logger.js';
import type { Result } from './result.js';

const log = logger.child({ module: 'http' });

export function sendErrorResponse(res: Response, error: AppError): void {
  res.status(error.status).json({
    error: { code: error.code, message: error.message, details: error.details },
  });
}

/** Writes `{ data }` for a successful result, or the error envelope otherwise. */
export function sendResult<T>(res: Response, result: Result<T, AppError>, status = 200): void {
  if (result.ok) {
    res.status(status).json({ data: result.value });
    return;
  }
  sendErrorResponse(res, result.error);
}

export function errorHandler(error: unknown, req: Request, res: Response, _next: NextFunction) {
  if (error instanceof AppError) {
    sendErrorResponse(res, error);
    return;
  }
  log.error({ err: error, method: req.method, path: req.path }, 'unhandled error');
  res.status(500).json({ error: { code: 'INTERNAL', message: 'Something went wrong' } });
}
