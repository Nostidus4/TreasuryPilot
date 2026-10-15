import { afterEach, expect, test, vi } from 'vitest';

import { api, rememberCsrfToken } from '@/lib/api/http';

const sentHeaders = async (call: () => Promise<unknown>) => {
  const fetch = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(new Response(null, { status: 204 }));
  await call();
  return new Headers(fetch.mock.calls[0][1]?.headers);
};

afterEach(() => {
  vi.restoreAllMocks();
  document.cookie = 'tp_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
  rememberCsrfToken(null);
});

test('writes echo the tp_csrf cookie in X-CSRF-Token', async () => {
  document.cookie = 'tp_csrf=cookie-token; path=/';
  const headers = await sentHeaders(() => api.post('/x'));
  expect(headers.get('X-CSRF-Token')).toBe('cookie-token');
});

test('without the cookie, writes send the token from the verify response', async () => {
  rememberCsrfToken('body-token');
  const headers = await sentHeaders(() => api.delete('/x'));
  expect(headers.get('X-CSRF-Token')).toBe('body-token');
});

test('reads send no CSRF header', async () => {
  document.cookie = 'tp_csrf=cookie-token; path=/';
  const headers = await sentHeaders(() => api.get('/x'));
  expect(headers.has('X-CSRF-Token')).toBe(false);
});
