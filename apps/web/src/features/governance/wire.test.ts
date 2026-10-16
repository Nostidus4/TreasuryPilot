import { describe, expect, it } from 'vitest';

import {
  toGovernanceTx,
  toTypedData,
  type GovernanceTxWire,
} from '@/features/governance/wire';

const call = {
  to: '0x1111111111111111111111111111111111111111',
  value: '0',
  data: '0x12345678abcd',
  operation: 0,
};

const wire: GovernanceTxWire = {
  id: 'tx-1',
  treasuryId: 'trs-1',
  purpose: 'PAYEE_ADD',
  safeAddress: '0x2222222222222222222222222222222222222222',
  ...call,
  nonce: 7,
  safeTxHash: `0x${'33'.repeat(32)}`,
  decodedCalls: [call, { ...call, operation: 1 }],
  humanSummary: 'Payee Add: call 1',
  typedData: {
    types: {
      EIP712Domain: [{ name: 'chainId', type: 'uint256' }],
      SafeTx: [{ name: 'nonce', type: 'uint256' }],
    },
    primaryType: 'SafeTx',
    domain: { chainId: 31337, verifyingContract: '0x22' },
    message: { nonce: 7, safeTxGas: 0 },
  },
  threshold: 2,
  owners: ['0xaaaa', '0xbbbb'],
  status: 'Ready',
  execTxHash: null,
  createdAt: '2030-01-01T00:00:00Z',
  signatures: [
    { owner: '0xaaaa', signature: '0x01', at: '2030-01-02T00:00:00Z' },
  ],
};

describe('governance wire mapper', () => {
  it('maps the API status, purpose and signatures to the view', () => {
    const view = toGovernanceTx(wire);
    expect(view).toMatchObject({
      id: 'tx-1',
      title: 'Register payee',
      summary: 'Payee Add: call 1',
      status: 'ReadyToExecute',
      nonce: 7,
      threshold: 2,
      txHash: undefined,
    });
    expect(view.signatures).toEqual([
      { owner: '0xaaaa', at: '2030-01-02T00:00:00Z' },
    ]);
    expect(view.owners.map((owner) => owner.address)).toEqual([
      '0xaaaa',
      '0xbbbb',
    ]);
  });

  it('keeps raw calls, including delegatecalls, and the sent tx hash', () => {
    const view = toGovernanceTx({
      ...wire,
      status: 'Submitted',
      execTxHash: `0x${'44'.repeat(32)}`,
    });
    expect(view.status).toBe('Executing');
    expect(view.txHash).toBe(`0x${'44'.repeat(32)}`);
    expect(view.calls.map((item) => item.operation)).toEqual([0, 1]);
    expect(view.calls[0]).toMatchObject({
      method: '0x12345678',
      data: call.data,
    });
  });

  it('hands the API typed data to signTypedData unmodified', () => {
    expect(toTypedData(wire)).toBe(wire.typedData);
  });
});
