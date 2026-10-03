import { describe, expect, it } from 'vitest';
import { formatDuration, formatTimeRange, isInFuture, toDayParam } from './format';

describe('format helpers', () => {
  it('formats a time range in UTC', () => {
    expect(formatTimeRange('2026-03-02T09:00:00.000Z', '2026-03-02T10:30:00.000Z')).toMatch(
      /09:00.*10:30/,
    );
  });

  it('formats durations', () => {
    expect(formatDuration('2026-03-02T09:00:00.000Z', '2026-03-02T09:30:00.000Z')).toBe('30 min');
    expect(formatDuration('2026-03-02T09:00:00.000Z', '2026-03-02T11:00:00.000Z')).toBe('2 h');
    expect(formatDuration('2026-03-02T09:00:00.000Z', '2026-03-02T10:30:00.000Z')).toBe('1 h 30 min');
  });

  it('extracts the UTC day parameter', () => {
    expect(toDayParam('2026-03-02T23:30:00.000Z')).toBe('2026-03-02');
  });

  it('compares against an injectable now', () => {
    const now = new Date('2026-03-02T09:00:00.000Z');
    expect(isInFuture('2026-03-02T09:30:00.000Z', now)).toBe(true);
    expect(isInFuture('2026-03-02T08:30:00.000Z', now)).toBe(false);
  });
});
