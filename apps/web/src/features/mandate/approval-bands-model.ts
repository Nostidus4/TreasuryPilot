import type { ApprovalBand } from '@/lib/api/types';
import { t } from '@/lib/i18n';
import { formatUnits, parseUnits } from '@/lib/money';

/** Bounded bands in order, then the unbounded last band ("above") as `lastK`. */
export interface BandsDraft {
  enabled: boolean;
  rows: Array<{ upTo: string; k: string }>;
  lastK: string;
}

export function bandsDraftFrom(
  bands: ApprovalBand[] | undefined,
  decimals: number,
): BandsDraft {
  if (!bands?.length) return { enabled: false, rows: [], lastK: '2' };
  const last = bands[bands.length - 1];
  return {
    enabled: true,
    rows: bands.slice(0, -1).map((band) => ({
      upTo: formatUnits(band.upTo ?? '0', decimals, { group: false }),
      k: String(band.k),
    })),
    lastK: String(last?.k ?? 2),
  };
}

// uint128 max is the contract's "unbounded" marker; a bounded band must stay below it.
const UNBOUNDED = (1n << 128n) - 1n;

/** Mirrors ThresholdApprovalExecutor.setBands; the API validates again. */
export function buildApprovalBands(
  draft: BandsDraft,
  decimals: number,
  approverCount: number,
): { bands?: ApprovalBand[]; error?: string } {
  if (!draft.enabled) return {};
  const k = (value: string) => (/^\d+$/.test(value) ? Number(value) : NaN);
  const bands: ApprovalBand[] = [];
  let previous: bigint | undefined;
  let previousK = 1;
  for (const row of draft.rows) {
    const parsed = parseUnits(row.upTo, decimals);
    const count = k(row.k);
    if (!parsed.ok || parsed.value >= UNBOUNDED) {
      return { error: t('Enter an amount for every band limit.') };
    }
    if (previous !== undefined && parsed.value <= previous) {
      return { error: t('Band limits must increase.') };
    }
    if (!Number.isInteger(count) || count < previousK) {
      return {
        error: t('Approvals must be at least 1 and never decrease.'),
      };
    }
    bands.push({ upTo: parsed.value.toString(), k: count });
    previous = parsed.value;
    previousK = count;
  }
  const lastK = k(draft.lastK);
  if (!Number.isInteger(lastK) || lastK < previousK) {
    return { error: t('Approvals must be at least 1 and never decrease.') };
  }
  bands.push({ k: lastK });
  if (bands.some((band) => band.k > approverCount)) {
    return { error: t('A band cannot need more approvals than approvers.') };
  }
  return { bands };
}
