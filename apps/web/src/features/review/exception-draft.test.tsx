import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import { ExceptionDraftView } from '@/features/review/exception-draft';
import type { ExceptionAiDraft } from '@/lib/api/types';

const draft: ExceptionAiDraft['draft'] = {
  summary: 'Pay 12,500 against a 10,000 cap.',
  reasons: [{ text: 'Over the cap by 2,500.', evidence_ids: ['excess'] }],
  alternatives: ['Split into parts.'],
};

test('renders summary, reasons and alternatives as text', () => {
  render(<ExceptionDraftView aiDraft={{ source: 'AI', draft }} />);
  expect(screen.getByText('Pay 12,500 against a 10,000 cap.')).toBeTruthy();
  expect(screen.getByText('Over the cap by 2,500.')).toBeTruthy();
  expect(screen.getByText('Split into parts.')).toBeTruthy();
  expect(screen.queryByText('Template')).toBeNull();
});

test('labels a template draft', () => {
  render(<ExceptionDraftView aiDraft={{ source: 'TEMPLATE', draft }} />);
  expect(screen.getByText('Template')).toBeTruthy();
});
