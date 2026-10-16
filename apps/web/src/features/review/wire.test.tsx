import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
    });
    expect(view.numbers).toEqual({
      requested: '3200000000',
      perRequestCap: '2000000000',
      overBy: '1200000000',
      dailyUsed: '2600000000',
      dailyLimit: '10000000000',
    });
  });

  it('maps exception statuses', () => {
    const row = (status: NonNullable<ExceptionWire['exception']>['status']) =>
      toExceptionDetail(
        {
          ...wire,
          exception: {
            id: 'e',
            requestId: 'req_1',
            status,
            governanceTxId: 'tx_1',
            reason: null,
            expiry: '',
            amount: '1',
            payee: '0x',
            mandateVersion: 1,
          },
        },
        'req_1',
      ).exception;
    expect(row('Proposed')).toMatchObject({
      status: 'GovernancePending',
      governanceTxId: 'tx_1',
    });
    expect(row('Granted').status).toBe('Granted');
    expect(row('Rejected').status).toBe('Rejected');
    expect(row('Expired').status).toBe('Closed');
  });

  it('builds the request bodies', () => {
    expect(toGrantBody(24)).toEqual({ expiryHours: 24 });
    expect(toRejectBody('  too high ')).toEqual({ reason: 'too high' });
    expect(grantedTxId({ governanceTx: { id: 'g1' } })).toBe('g1');
    expect(grantedTxId({ governanceTx: { governanceTx: { id: 'g2' } } })).toBe(
      'g2',
    );
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
