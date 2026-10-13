import { expect, test } from 'vitest';

import { formatBps, formatUnits, parseUnits, ratioPercent } from '@/lib/money';

test('formats base units without floats', () => {
  expect(formatUnits('1450000000', 6)).toBe('1,450.00');
  expect(formatUnits('303800000', 6)).toBe('303.80');
  expect(formatUnits('1', 6)).toBe('0.000001');
  expect(formatUnits('0', 6)).toBe('0.00');
  expect(formatUnits('123456789012345678901234567890', 6)).toBe(
    '123,456,789,012,345,678,901,234.56789',
  );
  expect(formatUnits('1450000000', 6, { group: false })).toBe('1450.00');
});

test('parses display amounts to exact base units', () => {
  expect(parseUnits('1,450.00', 6)).toEqual({ ok: true, value: 1450000000n });
  expect(parseUnits('0.1', 6)).toEqual({ ok: true, value: 100000n });
  expect(parseUnits('.5', 6)).toEqual({ ok: true, value: 500000n });
  // 0.1 + 0.2 is exact here, unlike with floats.
  const a = parseUnits('0.1', 6);
  const b = parseUnits('0.2', 6);
  expect(a.ok && b.ok && a.value + b.value).toBe(300000n);
});

test('rejects amounts the asset cannot represent', () => {
  expect(parseUnits('1.1234567', 6)).toEqual({
    ok: false,
    error: 'TOO_PRECISE',
  });
  expect(parseUnits('', 6)).toEqual({ ok: false, error: 'EMPTY' });
  expect(parseUnits('abc', 6)).toEqual({ ok: false, error: 'NOT_A_NUMBER' });
  expect(parseUnits('1e3', 6)).toEqual({ ok: false, error: 'NOT_A_NUMBER' });
  expect(parseUnits('-5', 6)).toEqual({ ok: false, error: 'NEGATIVE' });
});

test('round-trips every amount it formats', () => {
  for (const value of [
    '1',
    '999999',
    '1000000',
    '2600000000',
    '48215000000000',
  ]) {
    const parsed = parseUnits(formatUnits(value, 6), 6);
    expect(parsed).toEqual({ ok: true, value: BigInt(value) });
  }
});

test('ratio and basis points', () => {
  expect(ratioPercent('2600000000', '10000000000')).toBe(26);
  expect(ratioPercent('5', '0')).toBe(0);
  expect(ratioPercent('20', '10')).toBe(100);
  expect(formatBps(342)).toBe('3.42%');
});
