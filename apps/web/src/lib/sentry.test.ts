import { describe, expect, it } from 'vitest';

import { scrubBreadcrumb, scrubEvent } from '@/lib/sentry';

describe('sentry scrubbing', () => {
  it('drops the query string from the page URL and referer', () => {
    const event = scrubEvent({
      type: undefined,
      request: {
        url: 'https://app.example/auth/verify?token=magic-123#x',
        query_string: 'token=magic-123',
        headers: { Referer: 'https://app.example/login?token=magic-123' },
      },
    });

    expect(event.request).toEqual({
      url: 'https://app.example/auth/verify',
      headers: { Referer: 'https://app.example/login' },
    });
  });

  it('drops the query string from navigation and fetch breadcrumbs', () => {
    expect(
      scrubBreadcrumb({
        category: 'navigation',
        data: { from: '/auth/verify?token=magic-123', to: '/orgs' },
      }).data,
    ).toEqual({ from: '/auth/verify', to: '/orgs' });
    expect(
      scrubBreadcrumb({
        category: 'fetch',
        data: { url: '/api/auth?token=t', status_code: 200 },
      }).data,
    ).toEqual({ url: '/api/auth', status_code: 200 });
  });
});
