import type { NextFunction, Request, Response } from 'express';
import type { Actor, Role } from '../domain/types.js';
import { AppError, forbidden } from '../lib/errors.js';
import { sendError } from '../lib/http.js';
import * as userRepository from '../repositories/userRepository.js';

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      actor?: Actor;
    }
  }
}

export const SESSION_COOKIE = 'sid';

export async function requireAuth(req: Request, res: Response, next: NextFunction): Promise<void> {
  const token: unknown = req.cookies?.[SESSION_COOKIE];
  const actor = typeof token === 'string' ? await userRepository.findActorBySession(token) : undefined;
  if (!actor) {
    sendError(res, new AppError('UNAUTHENTICATED', 'Please sign in'));
    return;
  }
  req.actor = actor;
  next();
}

export function requireRole(...roles: Role[]) {
  return (req: Request, res: Response, next: NextFunction): void => {
    if (!req.actor || !roles.includes(req.actor.role)) {
      sendError(res, forbidden());
      return;
    }
    next();
  };
}

/** The authenticated actor; only valid behind `requireAuth`. */
export function actorOf(req: Request): Actor {
  if (!req.actor) throw new Error('actorOf() called on a route without requireAuth');
  return req.actor;
}
