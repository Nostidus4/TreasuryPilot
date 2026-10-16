import { expect, test } from 'vitest';

import { siweMessage } from '@/features/auth/api';

test('builds the SIWE message the API accepts', () => {
  const address = '0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC';
  const lines = siweMessage(
    address,
    11155111,
    'abc123',
    '2030-01-01T00:00:00.000Z',
  ).split('\n');

  expect(lines[0]).toBe(
    `${window.location.protocol}//${window.location.host} wants you to sign in with your Ethereum account:`,
  );
  expect(lines[1]).toBe(address);
  expect(lines).toContain('Link this wallet to TreasuryPilot');
  expect(lines).toContain(`URI: ${window.location.origin}`);
  expect(lines).toContain('Chain ID: 11155111');
  expect(lines).toContain('Nonce: abc123');
  expect(lines).toContain('Expiration Time: 2030-01-01T00:00:00.000Z');
});
