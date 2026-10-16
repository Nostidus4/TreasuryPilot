import type { components } from '@/lib/api/schema';
import type {
  DecodedCall,
  GovernanceStatus,
  GovernanceTxView,
  Hex,
  TypedData,
} from '@/lib/api/types';

export type GovernanceTxWire = components['schemas']['GovernanceTxView'];

/** API status enum -> the wording the UI uses (`Submitted` = sent, not yet mined). */
const statuses: Record<GovernanceTxWire['status'], GovernanceStatus> = {
  Collecting: 'AwaitingSignatures',
  Ready: 'ReadyToExecute',
  Submitted: 'Executing',
  Executed: 'Executed',
  Failed: 'Failed',
  Superseded: 'Superseded',
  Cancelled: 'Cancelled',
};

const purposes: Record<string, string> = {
  MODULE_SETUP: 'Set up the treasury module',
  MANDATE: 'Activate mandate',
  PAYEE_ADD: 'Register payee',
  PAYEE_DEACTIVATE: 'Deactivate payee',
  EXCEPTION_GRANT: 'Grant exception',
  EXCEPTION_REVOKE: 'Revoke exception',
  ALLOW_DUPLICATE: 'Allow duplicate invoice',
  CANCEL_REQUEST: 'Cancel request',
  PAUSE: 'Pause treasury',
  RESUME: 'Resume treasury',
  REVOKE: 'Revoke mandate',
  GUARDIAN_SETUP: 'Set up guardian',
};

/** The API only returns raw calls; the 4-byte selector is the most we can decode client-side. */
const toCall = (
  call: GovernanceTxWire['decodedCalls'][number],
): DecodedCall => ({
  to: call.to as Hex,
  toLabel: '',
  value: call.value,
  operation: call.operation === 1 ? 1 : 0,
  method: call.data.length >= 10 ? call.data.slice(0, 10) : 'transfer',
  params: [],
  data: call.data as Hex,
});

/** Owners carry no display name in the API; the address is shown instead. */
export function toGovernanceTx(wire: GovernanceTxWire): GovernanceTxView {
  return {
    id: wire.id,
    kind: wire.purpose,
    title: purposes[wire.purpose] ?? wire.purpose,
    summary: wire.humanSummary,
    status: statuses[wire.status],
    treasuryId: wire.treasuryId,
    safeAddress: wire.safeAddress as Hex,
    nonce: wire.nonce,
    threshold: wire.threshold,
    owners: wire.owners.map((address) => ({
      address: address as Hex,
      name: address,
    })),
    signatures: wire.signatures.map(({ owner, at }) => ({
      owner: owner as Hex,
      at,
    })),
    calls: wire.decodedCalls.map(toCall),
    safeTxHash: wire.safeTxHash as Hex,
    createdAt: wire.createdAt,
    txHash: (wire.execTxHash ?? undefined) as Hex | undefined,
  };
}

/** Passed to `signTypedData` exactly as the API built it. */
export const toTypedData = (wire: GovernanceTxWire) =>
  wire.typedData as unknown as TypedData;
