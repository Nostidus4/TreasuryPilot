import { expect, test } from 'vitest';

import { normalizeFeePolicy } from '@/features/treasury/api';
import type { FeePolicyResponse } from '@/lib/api/types';

// Captured from GET .../fee-policy (services/api mandate/fees.py get_fee_policy).
const real: FeePolicyResponse = {
  active: {
    preset: 'FAST',
    maxFeeMultiplierBps: 30000,
    tipPercentile: 75,
    perPlanThresholdWei: '1323000',
    dailyBudgetWei: '2646000',
    acceptedAt: '2026-10-14T10:00:00+00:00',
  },
  proposal: {
    id: '0192b1c0-0000-7000-8000-000000000001',
    preset: 'NORMAL',
    maxFeeMultiplierBps: 20000,
    tipPercentile: 50,
    perPlanThresholdWei: '5400000000000000',
    dailyBudgetWei: '10800000000000000',
    acceptedAt: null,
    proposedAt: '2026-10-14T11:00:00+00:00',
    basis: {
      avgPlanFee7dWei: '1800000000000000',
      p90PlanFee7dWei: '3100000000000000',
      plansPerDay7d: 4.5,
    },
  },
  spentTodayWei: '0',
  day: '2026-10-14',
  history: [
    {
      kind: 'PLAN_FEE',
      id: 'a',
      at: '2026-10-14T10:30:00+00:00',
      by: 'Linh',
      planId: 'p',
      estimatedFeeWei: '7',
      acceptedCapWei: '7',
    },
  ],
};

test('normalizeFeePolicy maps the real backend shape', () => {
  const policy = normalizeFeePolicy(real);
  expect(policy.proposalId).toBe(real.proposal!.id);
  expect(policy.basis).toEqual({
    avgPlanFeeWei: '1800000000000000',
    p90PlanFeeWei: '3100000000000000',
    plansPerDay: 4.5,
  });
  expect(policy.active?.preset).toBe('FAST');
  expect(policy.history).toHaveLength(1);
});

test('normalizeFeePolicy survives a response with no proposal or history', () => {
  const policy = normalizeFeePolicy({ active: null, proposal: null });
  expect(policy.proposalId).toBeNull();
  expect(policy.basis.avgPlanFeeWei).toBe('0');
  expect(policy.history).toEqual([]);
  expect(normalizeFeePolicy(undefined).spentTodayWei).toBe('0');
});
