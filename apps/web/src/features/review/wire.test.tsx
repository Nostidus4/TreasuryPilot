import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import type { PropsWithChildren } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { useException } from '@/features/operations/api';

import { StalePrompt } from '@/features/review/review-page';
import {
  grantedTxId,
  isStaleError,
  toExceptionDetail,
  toGrantBody,
  toRejectBody,
} from '@/features/review/wire';
import { ApiError } from '@/lib/api/http';
import type { ExceptionWire } from '@/lib/api/types';
import { newReviewItem, reviewView } from '@/mocks/db';
import { server } from '@/mocks/server';

const wire: ExceptionWire = {
  exception: null,
  numbers: {
    amount: '3200000000',
    cap: '2000000000',
    dailyUsed: '2600000000',
    dailyRemainingAfter: '4200000000',
    valueIfGranted: null,
  },
};

describe('exception wire mapping', () => {
  it('derives over-by and the daily limit from the API numbers', () => {
    const view = toExceptionDetail(wire, 'req_1');
    expect(view.exception).toEqual({
      requestId: 'req_1',
      status: 'Open',
      governanceTxId: undefined,
      grantTxFailed: false,
    });
    expect(view.numbers).toEqual({
      requested: '3200000000',
      perRequestCap: '2000000000',
      overBy: '1200000000',
      dailyUsed: '2600000000',
      dailyLimit: '10000000000',
    });
  });

  const row = (
    status: NonNullable<ExceptionWire['exception']>['status'],
    governanceTxStatus?: string,
  ) =>
    toExceptionDetail(
      {
        ...wire,
        exception: {
          id: 'e',
          requestId: 'req_1',
          status,
          governanceTxId: 'tx_1',
          governanceTxStatus,
          reason: null,
          expiry: '',
          amount: '1',
          payee: '0x',
          mandateVersion: 1,
        },
      },
      'req_1',
    ).exception;

  it('maps exception statuses', () => {
    expect(row('Requested').status).toBe('Open');
    expect(row('Proposed', 'Collecting')).toMatchObject({
      status: 'GovernancePending',
      governanceTxId: 'tx_1',
    });
    expect(row('Granted').status).toBe('Granted');
    expect(row('Rejected').status).toBe('Rejected');
    for (const status of ['Consumed', 'Revoked', 'Expired'] as const) {
      expect(row(status).status).toBe('Closed');
    }
  });

  it('makes a Proposed exception grantable again once its tx is dead', () => {
    for (const dead of ['Failed', 'Superseded', 'Cancelled']) {
      expect(row('Proposed', dead)).toMatchObject({
        status: 'Open',
        grantTxFailed: true,
        governanceTxId: 'tx_1',
      });
    }
  });

  it('keeps a negative daily remainder and clamps over-by at zero', () => {
    const view = toExceptionDetail(
      {
        ...wire,
        numbers: {
          ...wire.numbers,
          amount: '100',
          cap: '200',
          dailyRemainingAfter: '-50',
        },
      },
      'req_1',
    );
    expect(view.numbers.overBy).toBe('0');
    expect(view.numbers.dailyLimit).toBe((2600000000n + 100n - 50n).toString());
  });

  it('applies the wire mapping in useException', async () => {
    server.use(
      http.get('*/v1/orgs/o1/requests/r1/exception', () =>
        HttpResponse.json(wire),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useException('o1', 'r1'), {
      wrapper: ({ children }: PropsWithChildren) => (
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      ),
    });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.numbers.overBy).toBe('1200000000');
    expect(result.current.data?.exception.requestId).toBe('r1');
  });

  it('builds the request bodies', () => {
    expect(toGrantBody(24)).toEqual({ expiryHours: 24 });
    expect(toRejectBody('  too high ')).toEqual({ reason: 'too high' });
    expect(grantedTxId({ governanceTx: { id: 'g1' } })).toBe('g1');
    expect(grantedTxId({ governanceTx: { governanceTx: { id: 'g2' } } })).toBe(
      'g2',
    );
    expect(grantedTxId({ governanceTx: {} })).toBeUndefined();
  });
});

describe('allowed actions per role', () => {
  const item = newReviewItem({
    id: 'r',
    type: 'NEEDS_AUTHORITY',
    primaryCode: 'OVER_PER_REQUEST_LIMIT',
    treasuryId: 't',
  });
  it('offers the routed actions only to the routed role', () => {
    expect(reviewView(item, ['OWN']).allowedActions).toEqual([
      'GRANT_EXCEPTION',
      'CANCEL',
    ]);
    expect(reviewView(item, ['FIN']).allowedActions).toEqual([]);
  });
  it('offers nothing once resolved', () => {
    expect(
      reviewView({ ...item, status: 'Resolved' }, ['OWN']).allowedActions,
    ).toEqual([]);
  });
});

describe('stale items', () => {
  it('recognises the API stale conflicts', () => {
    const error = (code: string) =>
      new ApiError({ title: 't', status: 409, code, detail: 'd' });
    expect(isStaleError(error('STALE_ITEM'))).toBe(true);
    expect(isStaleError(error('EXCEPTION_TX_PENDING'))).toBe(true);
    expect(isStaleError(error('ACTION_NOT_ALLOWED'))).toBe(false);
    expect(isStaleError(error('REQUEST_NOT_ACTIVE'))).toBe(false);
    expect(isStaleError(error('EXCEPTION_ACTIVE'))).toBe(false);
    expect(isStaleError(new Error('x'))).toBe(false);
  });

  it('prompts a refresh that reloads the queue', () => {
    const onRefresh = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <StalePrompt orgId="o" onRefresh={onRefresh} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(onRefresh).toHaveBeenCalled();
  });
});
