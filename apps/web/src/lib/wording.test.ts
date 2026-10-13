import { expect, test } from 'vitest';

import '@/lib/i18n';
import {
  governanceStatus,
  mandateStatus,
  payeeStatus,
  planStatus,
  requestStatus,
  stepStatus,
  treasuryStatus,
} from '@/lib/status';

/**
 * Status-wording checklist (docs/modules/web §5, M16-D4, NFR-UX-04), signed
 * off in docs/modules/web/wording-checklist.md. Every status label the UI can
 * show is checked, not only the on-chain step states.
 */
const labels = (list: Array<{ label: string; tone: string }>) => list;

const all = {
  step: labels(
    [
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
    ].map((s) => stepStatus(s as Parameters<typeof stepStatus>[0], 3)),
  ),
  request: labels(
    [
      'Extracting',
      'Draft',
      'AwaitingApproval',
      'ChangesRequested',
      'Approved',
      'Scheduled',
      'InFlight',
      'Paid',
      'Rejected',
      'Cancelled',
    ].map((s) => requestStatus(s as Parameters<typeof requestStatus>[0])),
  ),
  governance: labels(
    [
      'AwaitingSignatures',
      'ReadyToExecute',
      'Executing',
      'Executed',
      'Failed',
      'Superseded',
    ].map((s) => governanceStatus(s as Parameters<typeof governanceStatus>[0])),
  ),
  plan: labels(
    [
      'Proposed',
      'Validated',
      'Executing',
      'Completed',
      'PartiallyCompleted',
      'Rejected',
    ].map((s) => planStatus(s as Parameters<typeof planStatus>[0])),
  ),
  payee: labels(
    [
      'Screening',
      'ScreeningHit',
      'AwaitingVerification',
      'AwaitingRegistration',
      'Cooling',
      'Active',
      'Deactivated',
    ].map((s) => payeeStatus(s as Parameters<typeof payeeStatus>[0])),
  ),
  mandate: labels(
    ['Draft', 'PendingActivation', 'Active', 'Superseded', 'Expired'].map((s) =>
      mandateStatus(s as Parameters<typeof mandateStatus>[0]),
    ),
  ),
  treasury: labels(
    ['Setup', 'Active', 'PauseRequested', 'Paused'].map((s) =>
      treasuryStatus(s as Parameters<typeof treasuryStatus>[0]),
    ),
  ),
};

test('no status label anywhere claims safe, done or guaranteed', () => {
  for (const [group, list] of Object.entries(all)) {
    for (const meta of list) {
      expect(meta.label, group).not.toMatch(/\b(safe|done|guaranteed)\b/i);
    }
  }
});

test('every label is non-empty and has a tone', () => {
  for (const list of Object.values(all)) {
    for (const meta of list) {
      expect(meta.label.trim()).not.toBe('');
      expect(meta.tone).toBeTruthy();
    }
  }
});

test('pausing and paused use the mandatory wording', () => {
  expect(treasuryStatus('PauseRequested').label).toBe('Pausing…');
  expect(treasuryStatus('Paused').label).toBe('Paused on-chain');
});

test('in-flight request and governance states do not claim payment', () => {
  expect(requestStatus('InFlight').label).toBe(
    'Sent — waiting for the network',
  );
  expect(governanceStatus('Executing').label).toBe(
    'Sent — waiting for the network',
  );
  expect(requestStatus('Approved').label).not.toMatch(/paid/i);
  expect(requestStatus('Scheduled').label).not.toMatch(/paid/i);
});
