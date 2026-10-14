import type { Breadcrumb, ErrorEvent } from '@sentry/react';

/** Magic links and redirects carry tokens in the query string; keep only the path. */
function stripQuery(url: string): string {
  return url.split(/[?#]/, 1)[0];
}

export function scrubEvent(event: ErrorEvent): ErrorEvent {
  const request = event.request;
  if (request) {
    if (request.url) request.url = stripQuery(request.url);
    delete request.query_string;
    if (request.headers?.Referer)
      request.headers.Referer = stripQuery(request.headers.Referer);
  }
  return event;
}

/** Navigation, fetch and xhr breadcrumbs record full URLs. */
export function scrubBreadcrumb(crumb: Breadcrumb): Breadcrumb {
  const data = crumb.data;
  if (data) {
    for (const key of ['url', 'from', 'to']) {
      if (typeof data[key] === 'string') data[key] = stripQuery(data[key]);
    }
  }
  return crumb;
}
