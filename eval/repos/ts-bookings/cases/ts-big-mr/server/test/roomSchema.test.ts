/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import { describe, expect, it } from 'vitest';
import { availabilityQuery, listRoomsQuery, updateRoomBody } from '../src/schemas/room.js';

describe('listRoomsQuery', () => {
  it.each([
    [{}, {}],
    [{ q: 'Aurora' }, { q: 'Aurora' }],
    [{ q: '  Aurora  ' }, { q: 'Aurora' }],
    [{ q: 'a'.repeat(60) }, { q: 'a'.repeat(60) }],
  ])('accepts %o', (query, parsed) => {
    expect(listRoomsQuery.parse(query)).toEqual(parsed);
  });

  it.each([{ q: '' }, { q: '   ' }, { q: 'a'.repeat(61) }])('rejects %o', (query) => {
    expect(listRoomsQuery.safeParse(query).success).toBe(false);
  });
});

describe('updateRoomBody', () => {
  it.each([
    { name: 'Borealis' },
    { capacity: 1 },
    { capacity: 500 },
    { hourlyRateCents: 0 },
    { maxDurationMinutes: 30 },
    { maxDurationMinutes: 720 },
    { name: 'Borealis', capacity: 12, hourlyRateCents: 3000, maxDurationMinutes: 240 },
  ])('accepts %o', (body) => {
    expect(updateRoomBody.safeParse(body).success).toBe(true);
  });

  it('trims the room name', () => {
    expect(updateRoomBody.parse({ name: '  Borealis ' })).toEqual({ name: 'Borealis' });
  });

  it.each([
    { name: '' },
    { name: 'a'.repeat(81) },
    { capacity: 0 },
    { capacity: 501 },
    { capacity: 2.5 },
    { hourlyRateCents: -1 },
    { hourlyRateCents: 99.5 },
    { maxDurationMinutes: 45 },
    { maxDurationMinutes: 750 },
  ])('rejects %o', (body) => {
    expect(updateRoomBody.safeParse(body).success).toBe(false);
  });

  it.each([{}, { active: false }])('rejects %o as having nothing to update', (body) => {
    const result = updateRoomBody.safeParse(body);
    expect(result.error?.issues.map((issue) => issue.message)).toEqual(['Nothing to update']);
  });
});

describe('availabilityQuery', () => {
  it('accepts a calendar day', () => {
    expect(availabilityQuery.parse({ day: '2026-03-02' })).toEqual({ day: '2026-03-02' });
  });

  it.each(['2026-3-2', '02.03.2026', '2026-03-02T00:00:00.000Z', ''])('rejects %j', (day) => {
    const result = availabilityQuery.safeParse({ day });
    expect(result.error?.issues.map((issue) => issue.message)).toEqual(['Expected YYYY-MM-DD']);
  });
});
