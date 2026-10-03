/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { FlagName } from './flags';

/** flags.ts reads VITE_FLAGS once at import time, so each case loads a fresh copy. */
async function loadFlags(value: string) {
  vi.stubEnv('VITE_FLAGS', value);
  vi.resetModules();
  const { flags } = await import('./flags');
  return flags;
}

function enabledOf(flags: Awaited<ReturnType<typeof loadFlags>>): FlagName[] {
  const all: FlagName[] = ['room-search', 'room-schedule', 'self-check-in'];
  return all.filter((name) => flags.isEnabled(name));
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('flags.isEnabled', () => {
  it.each<[string, FlagName[]]>([
    ['', []],
    ['room-search', ['room-search']],
    ['room-search,self-check-in', ['room-search', 'self-check-in']],
    [' room-schedule , self-check-in ', ['room-schedule', 'self-check-in']],
    [',room-search,,', ['room-search']],
    ['Room-Search,room-schedule-v2,unknown', []],
  ])('with VITE_FLAGS=%j enables %j', async (value, expected) => {
    expect(enabledOf(await loadFlags(value))).toEqual(expected);
  });
});
