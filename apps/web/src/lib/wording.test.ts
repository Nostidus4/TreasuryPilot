import { expect, test } from 'vitest';

import '@/lib/i18n';
import type { StepStatus } from '@/lib/api/types';
import {
  governanceStatus,
  governanceStatuses,
  mandateStatus,
  mandateStatuses,
  payeeStatus,
  payeeStatuses,
  planStatus,
  planStatuses,
  requestStatus,
  requestStatuses,
  stepStatus,
  treasuryStatus,
  treasuryStatuses,
} from '@/lib/status';

/**
 * Status-wording checklist (docs/modules/web §5, M16-D4, NFR-UX-04), signed
 * off in docs/modules/web/wording-checklist.md. Every status label the UI can
 * show is checked, not only the on-chain step states. The lists are derived
 * from the exhaustive status tables, so a new state is covered automatically.
 */
const keysOf = <S extends string>(table: Record<S, unknown>) =>
  Object.keys(table) as S[];

// `stepStatus` is a switch, so the compiler enforces this list is complete.
const stepStates = Object.keys({
  Planned: 0,
  Submitted: 0,
  Pending: 0,
  Confirmed: 0,
  Verified: 0,
  Final: 0,
  Dropped: 0,
  Replaced: 0,
  Unknown: 0,
  Failed: 0,
  Skipped: 0,
} satisfies Record<StepStatus, 0>) as StepStatus[];

const all = {
  step: stepStates.map((s) => stepStatus(s, 3)),
  request: keysOf(requestStatuses).map(requestStatus),
  governance: keysOf(governanceStatuses).map(governanceStatus),
  plan: keysOf(planStatuses).map(planStatus),
  payee: keysOf(payeeStatuses).map((status) => payeeStatus(status)),
  mandate: keysOf(mandateStatuses).map(mandateStatus),
  treasury: keysOf(treasuryStatuses).map(treasuryStatus),
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

test('Unknown is never styled as a failure', () => {
  expect(stepStatus('Unknown').tone).not.toBe('danger');
  expect(stepStatus('Unknown').label).not.toMatch(/fail|error|revert/i);
});
