import { describe, expect, it } from 'vitest';

import { toCreateBody, toPatchBody } from '@/features/requests/wire';

const input = {
  vendorId: 'v1',
  invoiceNumber: 'INV-1',
  amount: '1450000000',
  dueDate: '2030-11-05T23:59:59.000Z',
  description: 'Compute',
  treasuryId: 't1',
  earlyPayDate: '2030-10-30T23:59:59.000Z',
  earlyDiscountBps: 200,
};
const context = { assetId: 'a1', decimals: 6, payeeId: 'p1' };

describe('request wire mapping', () => {
  it('maps the form to the API create body', () => {
    expect(toCreateBody(input, context)).toEqual({
      treasuryId: 't1',
      vendorId: 'v1',
      payeeId: 'p1',
      assetId: 'a1',
      invoiceNo: 'INV-1',
      issueDate: expect.stringMatching(/^\d{4}-\d\d-\d\d$/) as string,
      dueDate: '2030-11-05',
      amount: '1450.00',
      note: 'Compute',
      terms: {
        netDueDay: 22223,
        discountBps: 200,
        discountDeadlineDay: 22217,
      },
    });
  });

  it('omits the discount without early terms and maps edits', () => {
    const body = toCreateBody(
      { ...input, earlyPayDate: undefined, earlyDiscountBps: undefined },
      context,
    );
    expect(body.terms).toEqual({ netDueDay: 22223 });
    expect(toPatchBody(input, 6)).toEqual({
      invoiceNo: 'INV-1',
      amount: '1450.00',
      dueDate: '2030-11-05',
      note: 'Compute',
    });
  });
});
