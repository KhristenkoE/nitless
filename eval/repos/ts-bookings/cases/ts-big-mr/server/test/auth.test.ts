/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Actor, Role } from '../src/domain/types.js';
import { actorOf, requireAuth, requireRole, SESSION_COOKIE } from '../src/middleware/auth.js';
import * as userRepository from '../src/repositories/userRepository.js';
import { mockRequest, mockResponse } from './support/express.js';

vi.mock('../src/repositories/userRepository.js');

const member: Actor = { id: 'u-1', role: 'member' };

describe('requireAuth', () => {
  beforeEach(() => {
    vi.mocked(userRepository.findActorBySession).mockReset();
  });

  it.each([
    ['there are no cookies', {}],
    ['the session cookie is missing', { cookies: {} }],
    ['the session cookie is not a string', { cookies: { [SESSION_COOKIE]: { token: 'abc' } } }],
  ])('responds with 401 without a lookup when %s', async (_case, request) => {
    const res = mockResponse();
    const next = vi.fn();

    await requireAuth(mockRequest(request), res, next);

    expect(userRepository.findActorBySession).not.toHaveBeenCalled();
    expect(res.status).toHaveBeenCalledWith(401);
    expect(next).not.toHaveBeenCalled();
  });

  it('responds with 401 when the session is unknown or expired', async () => {
    vi.mocked(userRepository.findActorBySession).mockResolvedValue(undefined);
    const req = mockRequest({ cookies: { [SESSION_COOKIE]: 'stale-token' } });
    const res = mockResponse();
    const next = vi.fn();

    await requireAuth(req, res, next);

    expect(userRepository.findActorBySession).toHaveBeenCalledWith('stale-token');
    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({
      error: { code: 'UNAUTHENTICATED', message: 'Please sign in', details: undefined },
    });
    expect(req.actor).toBeUndefined();
    expect(next).not.toHaveBeenCalled();
  });

  it('attaches the actor of a valid session and continues', async () => {
    vi.mocked(userRepository.findActorBySession).mockResolvedValue(member);
    const req = mockRequest({ cookies: { [SESSION_COOKIE]: 'valid-token' } });
    const res = mockResponse();
    const next = vi.fn();

    await requireAuth(req, res, next);

    expect(req.actor).toEqual(member);
    expect(next).toHaveBeenCalledOnce();
    expect(res.status).not.toHaveBeenCalled();
  });
});

describe('requireRole', () => {
  const staffOnly = requireRole('staff', 'admin');

  it.each<[Role, boolean]>([
    ['member', false],
    ['staff', true],
    ['admin', true],
  ])('%s is allowed: %s', (role, allowed) => {
    const req = mockRequest({ actor: { id: 'u-1', role } });
    const res = mockResponse();
    const next = vi.fn();

    staffOnly(req, res, next);

    expect(next).toHaveBeenCalledTimes(allowed ? 1 : 0);
    expect(res.status).toHaveBeenCalledTimes(allowed ? 0 : 1);
  });

  it('responds with 403 when no actor is attached', () => {
    const res = mockResponse();
    const next = vi.fn();

    staffOnly(mockRequest(), res, next);

    expect(res.status).toHaveBeenCalledWith(403);
    expect(res.json).toHaveBeenCalledWith({
      error: { code: 'FORBIDDEN', message: 'You are not allowed to do that', details: undefined },
    });
    expect(next).not.toHaveBeenCalled();
  });
});

describe('actorOf', () => {
  it('returns the authenticated actor', () => {
    expect(actorOf(mockRequest({ actor: member }))).toBe(member);
  });

  it('throws when used on a route without requireAuth', () => {
    expect(() => actorOf(mockRequest())).toThrow('actorOf() called on a route without requireAuth');
  });
});
