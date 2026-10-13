import { describe, expect, it } from 'vitest';

import { dueLabel, formatDate } from '@/lib/format';

describe('UTC calendar dates', () => {
  it('formats the UTC day regardless of the browser time zone', () => {
    // 23:30 UTC is already the next day in UTC+7 and still the same day in UTC-5.
    expect(formatDate('2026-10-15T23:30:00Z')).toBe('Oct 15, 2026');
    expect(formatDate('2026-10-16T00:00:00Z')).toBe('Oct 16, 2026');
  });

  it('counts due days between UTC calendar days', () => {
    const now = new Date('2026-10-13T23:59:00Z');
    expect(dueLabel('2026-10-14T00:00:00Z', now).text).toBe('Due in 1 day');
    expect(dueLabel('2026-10-13T00:00:00Z', now).text).toBe('Due today');
    expect(dueLabel('2026-10-12T12:00:00Z', now)).toMatchObject({
      text: 'Overdue by 1 day',
      overdue: true,
    });
  });
});
