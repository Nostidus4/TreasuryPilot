import type { Tone } from '@/components/ui/badge';
import type {
  GovernanceStatus,
  MandateStatus,
  PayeeStatus,
  PlanStatus,
  RequestStatus,
  StepStatus,
  TreasuryStatus,
} from '@/lib/api/types';
import { t } from '@/lib/i18n';

export interface StatusMeta {
  label: string;
  tone: Tone;
  /** Shows a pulsing dot: the state is still moving. */
  live?: boolean;
}

/**
 * Mandatory status wording (docs/modules/web §5, M16-D4, NFR-UX-04).
 * Never "safe", "done" or "guaranteed" without a verified state, and
 * Unknown is never presented as a failure.
 */
export function stepStatus(
  status: StepStatus,
  confirmations?: number,
): StatusMeta {
  switch (status) {
    case 'Planned':
      return { label: t('Planned'), tone: 'neutral' };
    case 'Submitted':
    case 'Pending':
      return {
        label: t('Sent — waiting for the network'),
        tone: 'info',
        live: true,
      };
    case 'Confirmed':
      return {
        label: t('Confirmed on-chain — verifying'),
        tone: 'info',
        live: true,
      };
    case 'Verified':
      return {
        label: t('Event matched checked fields · {{count}} confirmations', {
          count: confirmations ?? 0,
        }),
        tone: 'success',
      };
    case 'Final':
      return {
        label: t('Final · {{count}} confirmations', {
          count: confirmations ?? 0,
        }),
        tone: 'success',
      };
    case 'Unknown':
      return {
        label: t('Checking the chain — no new payment will be sent'),
        tone: 'warning',
        live: true,
      };
    case 'Dropped':
      return { label: t('Dropped by the network'), tone: 'warning' };
    case 'Replaced':
      return { label: t('Replaced by a newer transaction'), tone: 'neutral' };
    case 'Failed':
      return { label: t('Reverted on-chain'), tone: 'danger' };
    case 'Skipped':
      return { label: t('Not sent'), tone: 'neutral' };
  }
}

export const requestStatuses: Record<RequestStatus, StatusMeta> = {
  Extracting: { label: 'Reading document', tone: 'ai', live: true },
  Draft: { label: 'Draft', tone: 'neutral' },
  AwaitingApproval: { label: 'Awaiting approval', tone: 'warning' },
  ChangesRequested: { label: 'Changes requested', tone: 'warning' },
  Approved: { label: 'Approved', tone: 'success' },
  Scheduled: { label: 'Scheduled', tone: 'info' },
  InFlight: {
    label: 'Sent — waiting for the network',
    tone: 'info',
    live: true,
  },
  Paid: { label: 'Paid', tone: 'success' },
  Rejected: { label: 'Rejected', tone: 'danger' },
  Cancelled: { label: 'Cancelled', tone: 'neutral' },
};

export const governanceStatuses: Record<GovernanceStatus, StatusMeta> = {
  AwaitingSignatures: { label: 'Awaiting signatures', tone: 'warning' },
  ReadyToExecute: { label: 'Ready to execute', tone: 'info' },
  Executing: {
    label: 'Sent — waiting for the network',
    tone: 'info',
    live: true,
  },
  Executed: { label: 'Executed on-chain', tone: 'success' },
  Failed: { label: 'Reverted on-chain', tone: 'danger' },
  Superseded: { label: 'Superseded', tone: 'neutral' },
};

export const planStatuses: Record<PlanStatus, StatusMeta> = {
  Proposed: { label: 'Proposed', tone: 'neutral' },
  Validated: { label: 'Validated by policy', tone: 'info' },
  Executing: { label: 'Executing', tone: 'info', live: true },
  Completed: {
    label: 'All checked module event fields match',
    tone: 'success',
  },
  PartiallyCompleted: { label: 'Partially completed', tone: 'warning' },
  Rejected: { label: 'Rejected by policy', tone: 'danger' },
  Unknown: { label: 'Execution status unavailable', tone: 'warning' },
};

export const payeeStatuses: Record<PayeeStatus, StatusMeta> = {
  Screening: { label: 'Screening', tone: 'info', live: true },
  ScreeningHit: { label: 'Screening hit', tone: 'danger' },
  AwaitingVerification: { label: 'Needs out-of-band check', tone: 'warning' },
  AwaitingRegistration: { label: 'Ready to register', tone: 'info' },
  Cooling: { label: 'Cooling period', tone: 'warning', live: true },
  Active: { label: 'Active', tone: 'success' },
  Deactivated: { label: 'Deactivated', tone: 'neutral' },
};

export const mandateStatuses: Record<MandateStatus, StatusMeta> = {
  Draft: { label: 'Draft', tone: 'neutral' },
  PendingActivation: { label: 'Pending activation', tone: 'warning' },
  Active: { label: 'Active on-chain', tone: 'success' },
  Superseded: { label: 'Superseded', tone: 'neutral' },
  Expired: { label: 'Expired', tone: 'danger' },
};

export const treasuryStatuses: Record<TreasuryStatus, StatusMeta> = {
  Setup: { label: 'Setup in progress', tone: 'warning' },
  Active: { label: 'Operating', tone: 'success' },
  PauseRequested: { label: 'Pausing…', tone: 'warning', live: true },
  Paused: { label: 'Paused on-chain', tone: 'danger' },
};

const translate = (meta: StatusMeta): StatusMeta => ({
  ...meta,
  label: t(meta.label),
});

export const requestStatus = (status: RequestStatus) =>
  translate(requestStatuses[status]);
export const governanceStatus = (status: GovernanceStatus) =>
  translate(governanceStatuses[status]);
export const planStatus = (status: PlanStatus) =>
  translate(planStatuses[status]);
export const payeeStatus = (status: PayeeStatus) =>
  translate(payeeStatuses[status]);
export const mandateStatus = (status: MandateStatus) =>
  translate(mandateStatuses[status]);
export const treasuryStatus = (status: TreasuryStatus) =>
  translate(treasuryStatuses[status]);

export const roleLabels = {
  OWN: 'Owner',
  APR: 'Approver',
  OPR: 'Operator',
  FIN: 'Finance',
  GRD: 'Guardian',
  ADM: 'Org admin',
  AUD: 'Auditor',
} as const;
