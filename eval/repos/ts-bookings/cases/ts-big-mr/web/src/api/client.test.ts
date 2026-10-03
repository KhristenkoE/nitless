/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiClient } from './client';

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), init);
}

function lastRequest() {
  const [url, init] = fetchMock.mock.lastCall ?? [];
  return { url: String(url), init };
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe('apiClient', () => {
  it('sends GET requests with the defined query parameters and unwraps the data', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: [{ id: 'room-1' }] }));

    const rooms = await apiClient.get('/rooms', {
      q: 'Aurora',
      page: 2,
      active: true,
      day: undefined,
    });

    expect(rooms).toEqual([{ id: 'room-1' }]);
    expect(lastRequest()).toEqual({
      url: `${window.location.origin}/api/rooms?q=Aurora&page=2&active=true`,
      init: { method: 'GET', credentials: 'include', headers: undefined, body: undefined },
    });
  });

  it('sends a body as JSON', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'b-1' } }, { status: 201 }));

    const booking = await apiClient.post('/bookings', { roomId: 'room-1', title: 'Planning' });

    expect(booking).toEqual({ id: 'b-1' });
    expect(lastRequest().init).toEqual({
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: '{"roomId":"room-1","title":"Planning"}',
    });
  });

  it('omits the body and content type when there is nothing to send', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'b-1' } }));

    await apiClient.post('/bookings/b-1/cancel');

    expect(lastRequest()).toEqual({
      url: `${window.location.origin}/api/bookings/b-1/cancel`,
      init: { method: 'POST', credentials: 'include', headers: undefined, body: undefined },
    });
  });

  it('turns an error envelope into an ApiError', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: { code: 'CONFLICT', message: 'Slot taken', details: { roomId: 'room-1' } } },
        { status: 409 },
      ),
    );

    const request = apiClient.patch('/rooms/room-1', { capacity: 10 });

    await expect(request).rejects.toBeInstanceOf(ApiError);
    await expect(request).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      code: 'CONFLICT',
      message: 'Slot taken',
      details: { roomId: 'room-1' },
    });
  });

  it.each([
    [
      'is not JSON',
      () => new Response('<h1>Bad Gateway</h1>', { status: 502, statusText: 'Bad Gateway' }),
    ],
    ['has no error envelope', () => jsonResponse({}, { status: 404, statusText: 'Not Found' })],
  ])('falls back to the status text when the error body %s', async (_case, response) => {
    const res = response();
    fetchMock.mockResolvedValue(res);

    await expect(apiClient.delete('/bookings/b-1')).rejects.toMatchObject({
      status: res.status,
      code: 'UNKNOWN',
      message: res.statusText,
      details: undefined,
    });
  });
});
