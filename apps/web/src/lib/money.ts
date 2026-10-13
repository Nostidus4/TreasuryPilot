/**
 * Base-unit amounts <-> display strings, in integer math only (M16-D6).
 * No floats ever touch an amount.
 */

const groupThousands = (digits: string) =>
  digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');

export function toBigInt(value: string | bigint): bigint {
  return typeof value === 'bigint' ? value : BigInt(value);
}

/** `formatUnits(1450000000n, 6)` → `"1,450.00"`. */
export function formatUnits(
  value: string | bigint,
  decimals: number,
  { minFraction = 2, maxFraction = decimals, group = true } = {},
): string {
  const amount = toBigInt(value);
  const negative = amount < 0n;
  const digits = (negative ? -amount : amount)
    .toString()
    .padStart(decimals + 1, '0');
  const whole = digits.slice(0, digits.length - decimals);
  let fraction = decimals > 0 ? digits.slice(-decimals) : '';
  fraction = fraction.slice(0, maxFraction).replace(/0+$/, '');
  fraction = fraction.padEnd(Math.min(minFraction, maxFraction), '0');
  const body = `${group ? groupThousands(whole) : whole}${fraction ? `.${fraction}` : ''}`;
  return negative ? `-${body}` : body;
}

export type ParseResult =
  | { ok: true; value: bigint }
  | { ok: false; error: 'EMPTY' | 'NOT_A_NUMBER' | 'TOO_PRECISE' | 'NEGATIVE' };

/** Strict parse: rejects more fraction digits than the asset has. */
export function parseUnits(input: string, decimals: number): ParseResult {
  const text = input.replace(/[,\s]/g, '');
  if (text === '') return { ok: false, error: 'EMPTY' };
  if (text.startsWith('-')) return { ok: false, error: 'NEGATIVE' };
  if (!/^\d*\.?\d*$/.test(text) || text === '.') {
    return { ok: false, error: 'NOT_A_NUMBER' };
  }
  const [whole = '', fraction = ''] = text.split('.');
  if (fraction.length > decimals) return { ok: false, error: 'TOO_PRECISE' };
  return {
    ok: true,
    value: BigInt(`${whole || '0'}${fraction.padEnd(decimals, '0')}`),
  };
}

/** Integer percentage of `part` in `whole`, clamped to 0..100. */
export function ratioPercent(
  part: string | bigint,
  whole: string | bigint,
): number {
  const total = toBigInt(whole);
  if (total <= 0n) return 0;
  const basisPoints = (toBigInt(part) * 10000n) / total;
  return Math.max(0, Math.min(100, Number(basisPoints) / 100));
}

export function sum(values: Array<string | bigint>): bigint {
  return values.reduce<bigint>((total, value) => total + toBigInt(value), 0n);
}

/** Basis points → `"3.20%"`. */
export function formatBps(bps: number): string {
  return `${(bps / 100).toFixed(2)}%`;
}
