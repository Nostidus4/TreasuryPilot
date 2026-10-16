import type { Problem } from '@/lib/api/http';
import type { components } from '@/lib/api/schema';
import type {
  DiffEntry,
  MandateConfig,
  MandateDraft,
  MandateVersion,
} from '@/lib/api/types';
import { formatUnits } from '@/lib/money';

/** Wire shapes of `/mandates`: `schema.d.ts` types `config`, `diff` and `summary` loosely. */
export type MandateView = components['schemas']['MandateView'];
export type MandateDraftWire = components['schemas']['MandateDraftResponse'];

export const fromMandateView = (view: MandateView): MandateVersion => ({
  id: view.id,
  version: view.version,
  status: view.status as MandateVersion['status'],
  config: view.config as unknown as MandateConfig,
  createdAt: view.createdAt,
});

const directions = {
  looser: 'LOOSER',
  stricter: 'STRICTER',
  changed: 'NEUTRAL',
} as const;

const amountPath = /(^|\.)(perRequest|daily|minimum|target|minSupply)$/;

function show(path: string, value: unknown, decimals: number, symbol: string) {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string' && /^\d+$/.test(value) && amountPath.test(path))
    return `${formatUnits(value, decimals)} ${symbol}`;
  const text = (item: unknown) =>
    typeof item === 'string' ? item : JSON.stringify(item);
  return Array.isArray(value) ? value.map(text).join(', ') : text(value);
}

/**
 * The server renders the summary and the diff; this only reshapes them. A diff entry is
 * `{path, before, after, risk, requiresConfirmation}` with base-unit strings.
 */
export function fromDraftResponse(
  wire: MandateDraftWire,
  asset: { decimals: number; symbol: string },
): MandateDraft {
  return {
    draft: fromMandateView(wire.draft),
    summary: wire.summary.map((line) => line.text),
    diff: wire.diff.map((entry): DiffEntry => {
      const path = String(entry.path);
      return {
        field: path,
        before: show(path, entry.before, asset.decimals, asset.symbol),
        after: show(path, entry.after, asset.decimals, asset.symbol),
        direction:
          directions[entry.risk as keyof typeof directions] ?? 'NEUTRAL',
      };
    }),
    requiresConfirmation: wire.requiresConfirmation,
  };
}

/** Field errors from a 422: `errors` when present, else the API's `fields` names with the detail. */
export function fieldErrors(problem: Problem): Record<string, string> {
  if (problem.errors?.length)
    return Object.fromEntries(problem.errors.map((e) => [e.field, e.message]));
  return Object.fromEntries(
    (problem.fields ?? []).map((field) => [
      field,
      problem.detail ?? problem.title,
    ]),
  );
}
