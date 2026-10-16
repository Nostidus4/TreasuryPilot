import { isApiError } from '@/lib/api/http';
import type { ExceptionDetail, ExceptionWire } from '@/lib/api/types';

/** GET .../exception: the API's own exception row and base-unit numbers become the console view. */
const DEAD_TX = ['Failed', 'Superseded', 'Cancelled'];

export function toExceptionDetail(
  wire: ExceptionWire,
  requestId: string,
): ExceptionDetail {
  const { exception, numbers } = wire;
  const amount = BigInt(numbers.amount);
  const cap = BigInt(numbers.cap);
  const status = (() => {
    switch (exception?.status) {
      case undefined:
      case 'Requested':
        return 'Open';
      case 'Proposed':
        // A dead grant tx leaves the exception grantable again (API retry rule).
        return DEAD_TX.includes(exception.governanceTxStatus ?? '')
          ? 'Open'
          : 'GovernancePending';
      case 'Granted':
        return 'Granted';
      case 'Rejected':
        return 'Rejected';
      default:
        // Consumed, Expired, Invalidated, Revoked: nothing left to decide.
        return 'Closed';
    }
  })();
  return {
    exception: {
      requestId,
      status,
      governanceTxId: exception?.governanceTxId ?? undefined,
      grantTxFailed: status === 'Open' && Boolean(exception?.governanceTxId),
    },
    numbers: {
      requested: numbers.amount,
      perRequestCap: numbers.cap,
      overBy: (amount > cap ? amount - cap : 0n).toString(),
      dailyUsed: numbers.dailyUsed,
      // The API reports what is left after paying; the limit is the sum.
      dailyLimit: (
        BigInt(numbers.dailyUsed) +
        amount +
        BigInt(numbers.dailyRemainingAfter)
      ).toString(),
    },
    aiDraft: wire.aiDraft ?? null,
  };
}

/** `POST .../exception/grant-tx` body. */
export const toGrantBody = (expiryHours: number) => ({ expiryHours });

/** `POST .../exception/reject` body. */
export const toRejectBody = (reason: string) => ({ reason: reason.trim() });

/** 409s that mean the item moved on under the user; the answer is to refresh. */
const STALE_CODES = ['STALE_ITEM', 'EXCEPTION_EXISTS', 'EXCEPTION_TX_PENDING'];

export const isStaleError = (error: unknown) =>
  STALE_CODES.some((code) => isApiError(error, code));

/** The governance transaction id from a grant response, nested or flat. */
export function grantedTxId(response: {
  governanceTx: { id?: string; governanceTx?: { id: string } };
}): string | undefined {
  const tx = response.governanceTx;
  return tx.governanceTx?.id ?? tx.id;
}
