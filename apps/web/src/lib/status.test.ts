import { expect, test } from 'vitest';

import '@/lib/i18n';
import type { StepStatus } from '@/lib/api/types';
import { stepStatus } from '@/lib/status';

// The mandatory wording table: docs/modules/web §5 (M16-D4, NFR-UX-04).
test('uses the mandatory status wording', () => {
  expect(stepStatus('Submitted').label).toBe('Sent — waiting for the network');
  expect(stepStatus('Pending').label).toBe('Sent — waiting for the network');
  expect(stepStatus('Confirmed').label).toBe('Confirmed on-chain — verifying');
  expect(stepStatus('Verified', 3).label).toBe('Paid · 3 confirmations');
  expect(stepStatus('Final', 64).label).toBe('Paid · 64 confirmations · Final');
  expect(stepStatus('Unknown').label).toBe(
    'Checking the chain — no new payment will be sent',
  );
});

test('never presents Unknown as a failure', () => {
  expect(stepStatus('Unknown').tone).not.toBe('danger');
  expect(stepStatus('Failed').tone).toBe('danger');
});

test('never claims safe, done or guaranteed', () => {
  const all: StepStatus[] = [
    'Planned',
    'Submitted',
    'Pending',
    'Confirmed',
    'Verified',
    'Final',
    'Dropped',
    'Replaced',
    'Unknown',
    'Failed',
    'Skipped',
  ];
  for (const status of all) {
    expect(stepStatus(status, 3).label).not.toMatch(
      /\b(safe|done|guaranteed)\b/i,
    );
  }
});

test('only verified states read as paid', () => {
  for (const status of [
    'Submitted',
    'Pending',
    'Confirmed',
    'Unknown',
  ] as const) {
    expect(stepStatus(status).label).not.toMatch(/paid/i);
    expect(stepStatus(status).tone).not.toBe('success');
  }
});
