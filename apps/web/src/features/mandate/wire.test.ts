import { describe, expect, test } from 'vitest';

import {
  fieldErrors,
  fromDraftResponse,
  type MandateDraftWire,
} from '@/features/mandate/wire';

const asset = { decimals: 6, symbol: 'USDC' };

const wire = (
  diff: Array<Record<string, unknown>>,
  requiresConfirmation: boolean,
): MandateDraftWire => ({
  draft: {
    id: '0191f0f0-0000-7000-8000-000000000001',
    treasuryId: 't',
    version: 4,
    status: 'Draft',
    config: { limits: { PAY: { perRequest: '2500500000', daily: '1' } } },
    configHash: '0x00',
    createdAt: '2026-10-16T00:00:00Z',
  },
  summary: [
    {
      field: 'limits.PAY',
      text: 'PAY: up to 2,500.50 USDC per request (2500500000 base units).',
    },
  ],
  diff,
  requiresConfirmation,
  bundlePreview: {},
});

describe('mandate wire mapping', () => {
  test('keeps the draft id and the base units the server saved next to its summary text', () => {
    const draft = fromDraftResponse(wire([], false), asset);
    expect(draft.draft.id).toBe('0191f0f0-0000-7000-8000-000000000001');
    expect(draft.draft.config.limits.PAY.perRequest).toBe('2500500000');
    expect(draft.summary[0]).toContain('2,500.50 USDC');
    expect(draft.summary[0]).toContain('2500500000');
  });

  test('a looser change needs confirmation and shows human amounts', () => {
    const draft = fromDraftResponse(
      wire(
        [
          {
            path: 'limits.PAY.perRequest',
            before: '2000000000',
            after: '2500500000',
            risk: 'looser',
            requiresConfirmation: true,
          },
        ],
        true,
      ),
      asset,
    );
    expect(draft.requiresConfirmation).toBe(true);
    expect(draft.diff).toEqual([
      {
        field: 'limits.PAY.perRequest',
        before: '2,000.00 USDC',
        after: '2,500.50 USDC',
        direction: 'LOOSER',
      },
    ]);
  });

  test('a stricter-only change needs no confirmation; a new executor does', () => {
    const stricter = fromDraftResponse(
      wire(
        [
          {
            path: 'limits.PAY.perRequest',
            before: '2000000000',
            after: '1500000000',
            risk: 'stricter',
            requiresConfirmation: false,
          },
        ],
        false,
      ),
      asset,
    );
    expect(stricter.requiresConfirmation).toBe(false);
    expect(stricter.diff[0].direction).toBe('STRICTER');

    const executor = fromDraftResponse(
      wire(
        [
          {
            path: 'executor',
            before: '0xaa',
            after: '0xbb',
            risk: 'changed',
            requiresConfirmation: true,
          },
        ],
        true,
      ),
      asset,
    );
    expect(executor.diff[0].direction).toBe('NEUTRAL');
    expect(executor.requiresConfirmation).toBe(true);
  });

  test('422 field names become per-field messages', () => {
    expect(
      fieldErrors({
        title: 'Mandate validation failed',
        status: 422,
        code: 'MANDATE_INCOMPLETE',
        detail: 'The mandate draft is missing required fields.',
        fields: ['executor'],
      }),
    ).toEqual({ executor: 'The mandate draft is missing required fields.' });
  });
});
