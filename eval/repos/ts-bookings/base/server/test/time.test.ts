import { describe, expect, it } from 'vitest';
import {
  addMinutes,
  isOnSlotBoundary,
  minutesBetween,
  startOfUtcDay,
  toInstant,
  utcDay,
  utcDayOfWeek,
} from '../src/lib/time.js';

describe('time helpers', () => {
  it('normalises instants to UTC ISO strings', () => {
    expect(toInstant('2026-03-02T10:30:00+01:00')).toBe('2026-03-02T09:30:00.000Z');
    expect(toInstant(new Date(Date.UTC(2026, 2, 2, 9, 30)))).toBe('2026-03-02T09:30:00.000Z');
  });

  it('adds minutes across day boundaries', () => {
    expect(addMinutes('2026-03-02T23:30:00.000Z', 45)).toBe('2026-03-03T00:15:00.000Z');
  });

  it('counts whole minutes between instants', () => {
    expect(minutesBetween('2026-03-02T09:00:00.000Z', '2026-03-02T10:30:00.000Z')).toBe(90);
    expect(minutesBetween('2026-03-02T10:30:00.000Z', '2026-03-02T09:00:00.000Z')).toBe(-90);
  });

  it('computes UTC days', () => {
    expect(startOfUtcDay('2026-03-02T23:59:00.000Z')).toBe('2026-03-02T00:00:00.000Z');
    expect(utcDay('2026-03-07')).toBe('2026-03-07T00:00:00.000Z');
    expect(utcDayOfWeek('2026-03-07T12:00:00.000Z')).toBe(6);
  });

  it('checks slot boundaries', () => {
    expect(isOnSlotBoundary('2026-03-02T09:30:00.000Z', 30)).toBe(true);
    expect(isOnSlotBoundary('2026-03-02T09:45:00.000Z', 30)).toBe(false);
    expect(isOnSlotBoundary('2026-03-02T09:30:01.000Z', 30)).toBe(false);
  });
});
