import { Plus, Trash2 } from 'lucide-react';

import { AmountInput } from '@/components/domain/amount';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Field, Input } from '@/components/ui/input';
import type { BandsDraft } from '@/features/mandate/approval-bands-model';
import { t } from '@/lib/i18n';

export function ApprovalBandsEditor({
  draft,
  onChange,
  error,
  symbol,
}: {
  draft: BandsDraft;
  onChange: (next: BandsDraft) => void;
  error?: string;
  symbol: string;
}) {
  const setRow = (index: number, patch: Partial<BandsDraft['rows'][number]>) =>
    onChange({
      ...draft,
      rows: draft.rows.map((row, i) =>
        i === index ? { ...row, ...patch } : row,
      ),
    });
  return (
    <Card>
      <CardHeader
        title={t('Approval thresholds')}
        description={t(
          'Larger payments can need more distinct approvers. Without bands, one approval is enough.',
        )}
      />
      <CardContent className="grid gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(event) =>
              onChange({
                ...draft,
                enabled: event.target.checked,
                rows:
                  event.target.checked && draft.rows.length === 0
                    ? [{ upTo: '10000', k: '1' }]
                    : draft.rows,
              })
            }
          />
          {t('Require multiple approvals by amount')}
        </label>
        {draft.enabled && (
          <>
            {draft.rows.map((row, index) => (
              <div key={index} className="flex items-end gap-2">
                <Field
                  htmlFor={`band-upto-${index}`}
                  label={t('Up to ({{symbol}})', { symbol })}
                >
                  <AmountInput
                    id={`band-upto-${index}`}
                    value={row.upTo}
                    onChange={(event) =>
                      setRow(index, { upTo: event.target.value })
                    }
                  />
                </Field>
                <Field htmlFor={`band-k-${index}`} label={t('Approvals')}>
                  <Input
                    id={`band-k-${index}`}
                    inputMode="numeric"
                    className="w-20"
                    value={row.k}
                    onChange={(event) =>
                      setRow(index, { k: event.target.value })
                    }
                  />
                </Field>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t('Remove band {{index}}', { index: index + 1 })}
                  onClick={() =>
                    onChange({
                      ...draft,
                      rows: draft.rows.filter((_, i) => i !== index),
                    })
                  }
                >
                  <Trash2 aria-hidden="true" />
                </Button>
              </div>
            ))}
            <Field
              htmlFor="band-k-last"
              label={t('Approvals above the last limit')}
              error={error}
            >
              <Input
                id="band-k-last"
                inputMode="numeric"
                className="w-20"
                value={draft.lastK}
                aria-invalid={Boolean(error)}
                onChange={(event) =>
                  onChange({ ...draft, lastK: event.target.value })
                }
              />
            </Field>
            <div>
              <Button
                onClick={() =>
                  onChange({
                    ...draft,
                    rows: [...draft.rows, { upTo: '', k: '1' }],
                  })
                }
              >
                <Plus aria-hidden="true" />
                {t('Add band')}
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
