/**
 * Thin fetch wrapper for the v1 REST API (docs/API_SPEC.md §0):
 * cookie session, RFC 9457 problem responses, Idempotency-Key and If-Match.
 */

export interface Problem {
  type?: string;
  title: string;
  status: number;
  code: string;
  detail?: string;
  errors?: Array<{ field: string; message: string }>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail ?? problem.title);
    this.name = 'ApiError';
    this.status = problem.status;
    this.code = problem.code;
    this.problem = problem;
  }
}

export function isApiError(error: unknown, code?: string): error is ApiError {
  return error instanceof ApiError && (code ? error.code === code : true);
}

/** A message that is safe to show to the user for any thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return 'Something went wrong. Try again.';
}

const apiRoot = `${import.meta.env.VITE_API_URL ?? ''}/v1`;

interface RequestOptions {
  body?: unknown;
  form?: FormData;
  idempotent?: boolean;
  ifMatch?: string;
  query?: Record<string, string | number | boolean | undefined>;
  signal?: AbortSignal;
}

export function apiUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(`${apiRoot}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== '')
      url.searchParams.set(key, String(value));
  }
  return url.toString();
}

async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers({ Accept: 'application/json' });
  if (options.body !== undefined)
    headers.set('Content-Type', 'application/json');
  if (method !== 'GET') headers.set('X-CSRF-Token', 'web');
  if (options.idempotent) headers.set('Idempotency-Key', crypto.randomUUID());
  if (options.ifMatch) headers.set('If-Match', options.ifMatch);

  let response: Response;
  try {
    response = await fetch(apiUrl(path, options.query), {
      method,
      headers,
      credentials: 'include',
      signal: options.signal,
      body:
        options.form ??
        (options.body !== undefined ? JSON.stringify(options.body) : undefined),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError')
      throw cause;
    throw new ApiError({
      title: 'Network error',
      status: 0,
      code: 'NETWORK_ERROR',
      detail: 'Cannot reach the TreasuryPilot API. Check your connection.',
    });
  }

  if (
    response.status === 204 ||
    (response.status === 202 && response.headers.get('Content-Length') === '0')
  ) {
    return undefined as T;
  }

  const text = await response.text();
  const payload: unknown = text ? JSON.parse(text) : undefined;

  if (!response.ok) {
    const problem = (payload ?? {}) as Partial<Problem>;
    throw new ApiError({
      title: problem.title ?? response.statusText,
      status: response.status,
      code: problem.code ?? `HTTP_${response.status}`,
      detail: problem.detail,
      errors: problem.errors,
    });
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>('GET', path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('POST', path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('PATCH', path, { ...options, body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>('DELETE', path, options),
  upload: <T>(path: string, form: FormData) =>
    request<T>('POST', path, { form, idempotent: true }),
};
