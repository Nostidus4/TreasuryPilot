import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { expect, test } from 'vitest';

import { ApprovalBandsEditor } from '@/features/mandate/approval-bands';
import {
  bandsDraftFrom,
  buildApprovalBands,
  type BandsDraft,
} from '@/features/mandate/approval-bands-model';

const draft = (rows: BandsDraft['rows'], lastK = '2'): BandsDraft => ({
  enabled: true,
  rows,
  lastK,
});

test('builds base-unit bands with an unbounded last band', () => {
  expect(buildApprovalBands(draft([{ upTo: '1000.5', k: '1' }]), 6, 2)).toEqual(
    { bands: [{ upTo: '1000500000', k: 1 }, { k: 2 }] },
  );
  expect(buildApprovalBands({ ...draft([]), enabled: false }, 6, 2)).toEqual(
    {},
  );
});

test.each([
  [
    'limits that do not increase',
    draft([
      { upTo: '5', k: '1' },
      { upTo: '5', k: '2' },
    ]),
  ],
  ['a decreasing k', draft([{ upTo: '5', k: '2' }], '1')],
  ['a zero k', draft([{ upTo: '5', k: '0' }])],
  ['a k above the approver count', draft([{ upTo: '5', k: '1' }], '3')],
  ['an empty limit', draft([{ upTo: '', k: '1' }])],
])('rejects %s', (_name, value) => {
  expect(buildApprovalBands(value, 6, 2).error).toBeTruthy();
});

test('round-trips stored bands into the form', () => {
  const stored = [{ upTo: '1000000', k: 1 }, { k: 2 }];
  const round = buildApprovalBands(bandsDraftFrom(stored, 6), 6, 2);
  expect(round.bands).toEqual(stored);
});

test('the editor adds a band row', () => {
  function Harness() {
    const [value, setValue] = useState(draft([{ upTo: '10', k: '1' }]));
    return (
      <ApprovalBandsEditor draft={value} onChange={setValue} symbol="USDC" />
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Harness />
    </QueryClientProvider>,
  );
  expect(screen.getAllByLabelText(/Up to/)).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Add band' }));
  expect(screen.getAllByLabelText(/Up to/)).toHaveLength(2);
});
