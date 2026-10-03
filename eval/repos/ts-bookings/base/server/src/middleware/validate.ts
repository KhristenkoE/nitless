import type { NextFunction, Request, Response } from 'express';
import type { ZodTypeAny } from 'zod';
import { AppError } from '../lib/errors.js';
import { sendError } from '../lib/http.js';

/** Parses `req.body` with `schema` and replaces it with the parsed value. */
export function validateBody(schema: ZodTypeAny) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const parsed = schema.safeParse(req.body);
    if (!parsed.success) {
      sendError(res, new AppError('VALIDATION', 'Invalid request body', parsed.error.flatten()));
      return;
    }
    req.body = parsed.data;
    next();
  };
}

/** Parses `req.query` with `schema` into `res.locals.query` (req.query is read-only in Express 5). */
export function validateQuery(schema: ZodTypeAny) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const parsed = schema.safeParse(req.query);
    if (!parsed.success) {
      sendError(res, new AppError('VALIDATION', 'Invalid query string', parsed.error.flatten()));
      return;
    }
    res.locals.query = parsed.data;
    next();
  };
}
