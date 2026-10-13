import { delay, http, HttpResponse, type HttpHandler } from 'msw';

import type { Problem } from '@/lib/api/http';
import type { Hex } from '@/lib/api/types';
import { db, tick } from '@/mocks/db';

export class MockProblem extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    detail: string,
    readonly errors?: Problem['errors'],
    readonly headers?: Record<string, string>,
  ) {
    super(detail);
  }
}

/** Throw to answer with an RFC 9457 problem document. */
export function fail(
  status: number,
  code: string,
  detail: string,
  errors?: Problem['errors'],
  headers?: Record<string, string>,
): never {
  throw new MockProblem(status, code, detail, errors, headers);
}

interface Context<Body> {
  params: Record<string, string>;
  query: URLSearchParams;
  body: Body;
  request: Request;
}

type Method = 'get' | 'post' | 'patch' | 'delete';

interface RouteOptions {
  public?: boolean;
  status?: number;
  /** The handler reads the raw request itself (multipart uploads). */
  raw?: boolean;
}

export function route<Body = undefined>(
  method: Method,
  path: string,
  handler: (context: Context<Body>) => unknown,
  options: RouteOptions = {},
): HttpHandler {
  return http[method](`*/v1${path}`, async ({ params, request }) => {
    await delay(120 * db.timeScale);
    tick();
    try {
      if (!options.public && !db.session) {
        fail(401, 'UNAUTHENTICATED', 'Your session has ended. Sign in again.');
      }
      let body: unknown;
      if (!options.raw && method !== 'get' && method !== 'delete') {
        const text = await request.text();
        body = text ? (JSON.parse(text) as unknown) : {};
      }
      const result = await handler({
        params: params as Record<string, string>,
        query: new URL(request.url).searchParams,
        body: body as Body,
        request,
      });
      if (result instanceof Response) return result;
      if (result === undefined) {
        return new HttpResponse(null, { status: options.status ?? 204 });
      }
      return HttpResponse.json(result as Record<string, unknown>, {
        status: options.status ?? 200,
      });
    } catch (error) {
      if (error instanceof MockProblem) {
        const problem: Problem = {
          type: `https://treasurypilot.dev/problems/${error.code}`,
          title: error.code,
          status: error.status,
          code: error.code,
          detail: error.message,
          errors: error.errors,
        };
        return HttpResponse.json(problem, {
          status: error.status,
          headers: {
            'Content-Type': 'application/problem+json',
            ...error.headers,
          },
        });
      }
      throw error;
    }
  });
}

export function find<T>(
  items: T[],
  predicate: (item: T) => boolean,
  what: string,
): T {
  const item = items.find(predicate);
  if (!item) fail(404, 'NOT_FOUND', `${what} was not found.`);
  return item;
}

export const isAddress = (value: unknown): value is Hex =>
  typeof value === 'string' && /^0x[0-9a-fA-F]{40}$/.test(value);

export const sameAddress = (a: string, b: string) =>
  a.toLowerCase() === b.toLowerCase();

export const isLinked = (address: string) =>
  db.linkedWallets.some((wallet) => sameAddress(wallet.address, address));

export const isoNow = () => new Date().toISOString();
