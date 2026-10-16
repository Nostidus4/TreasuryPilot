import { describe, expect, it } from 'vitest';

import {
  toApiTerms,
  toCreateBody,
  toPatchBody,
} from '@/features/requests/wire';

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

  it('caps the issue date at the due date when it is already past', () => {
    const body = toCreateBody(
      { ...input, dueDate: '2001-01-05T23:59:59.000Z' },
      context,
    );
    expect(body.issueDate).toBe('2001-01-05');
  });

  it('pulls an existing issue date back only when the due date moves before it', () => {
    expect(toPatchBody(input, 6, '2030-12-01')).toMatchObject({
      issueDate: '2030-11-05',
    });
    expect(toPatchBody(input, 6, '2030-10-01')).not.toHaveProperty('issueDate');
    expect(toPatchBody(input, 6)).not.toHaveProperty('issueDate');
  });

  it('formats amounts with the asset decimals', () => {
    const wei = '1450123456789012345678';
    expect(
      toCreateBody({ ...input, amount: wei }, { ...context, decimals: 18 })
        .amount,
    ).toBe('1450.123456789012345678');
    expect(toPatchBody({ ...input, amount: wei }, 18).amount).toBe(
      '1450.123456789012345678',
    );
  });

  it('sends a discount only when both early fields are set', () => {
    expect(
      toApiTerms({ dueDate: input.dueDate, earlyPayDate: input.earlyPayDate }),
    ).toEqual({
      netDueDay: 22223,
    });
    expect(
      toApiTerms({ dueDate: input.dueDate, earlyDiscountBps: 200 }),
    ).toEqual({
      netDueDay: 22223,
    });
  });
});
