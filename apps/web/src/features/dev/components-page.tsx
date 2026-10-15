import { Inbox, Plus, Trash2 } from 'lucide-react';
import { useState, type ReactNode } from 'react';

import { Amount } from '@/components/domain/amount';
import { Address, TxHash } from '@/components/domain/chain';
import {
  BalanceMeter,
  DiffView,
  KeyValueList,
  UsageBar,
} from '@/components/domain/display';
import {
  AiExplanation,
  PolicyDecision,
  StatusBadge,
} from '@/components/domain/status';
import { EmptyState, ErrorState, ListSkeleton } from '@/components/feedback';
import { Badge, type Tone } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Checkbox,
  RadioCard,
  RadioGroup,
  Select,
  Switch,
} from '@/components/ui/controls';
import { Field, Input, Textarea } from '@/components/ui/input';
import { Alert, Kbd, Skeleton } from '@/components/ui/misc';
import { t } from '@/lib/i18n';
import { requestStatus } from '@/lib/status';

const tones: Tone[] = [
  'neutral',
  'success',
  'warning',
  'danger',
  'info',
  'ai',
  'outline',
];

function Section({ children, title }: { children: ReactNode; title: string }) {
  return (
    <Card>
      <CardHeader title={title} />
      <CardContent className="grid gap-4">{children}</CardContent>
    </Card>
  );
}

/** Every primitive once, so a theme change can be reviewed in one place. */
function Gallery({ id }: { id: string }) {
  const [option, setOption] = useState('standard');
  const [asset, setAsset] = useState('usdc');
  return (
    <div className="grid content-start gap-4">
      <Section title={t('Buttons')}>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary">
            <Plus aria-hidden="true" />
            {t('Primary')}
          </Button>
          <Button>{t('Secondary')}</Button>
          <Button variant="ghost">{t('Ghost')}</Button>
          <Button variant="danger">{t('Danger')}</Button>
          <Button variant="danger-outline">
            <Trash2 aria-hidden="true" />
            {t('Danger outline')}
          </Button>
          <Button variant="link">{t('Link')}</Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm">{t('Small')}</Button>
          <Button size="lg">{t('Large')}</Button>
          <Button variant="primary" loading>
            {t('Loading')}
          </Button>
          <Button disabled>{t('Disabled')}</Button>
          <span className="text-sm text-muted-foreground">
            {t('Search')} <Kbd>⌘K</Kbd>
          </span>
        </div>
      </Section>

      <Section title={t('Badges and status')}>
        <div className="flex flex-wrap gap-2">
          {tones.map((tone) => (
            <Badge key={tone} tone={tone}>
              {tone}
            </Badge>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {(
            [
              'Draft',
              'AwaitingApproval',
              'Approved',
              'Scheduled',
              'Paid',
              'Rejected',
            ] as const
          ).map((status) => (
            <StatusBadge key={status} meta={requestStatus(status)} />
          ))}
        </div>
      </Section>

      <Section title={t('Alerts')}>
        {(['info', 'success', 'warning', 'danger', 'ai'] as const).map(
          (tone) => (
            <Alert key={tone} tone={tone} title={`${tone} alert`}>
              {t('One sentence that says what happened and what to do.')}
            </Alert>
          ),
        )}
      </Section>

      <Section title={t('Form controls')}>
        <Field htmlFor={`${id}-input`} label={t('Text input')} hint="Hint">
          <Input id={`${id}-input`} placeholder="you@company.com" />
        </Field>
        <Field
          htmlFor={`${id}-invalid`}
          label={t('Invalid input')}
          error={t('Enter a 0x address with 40 hex characters.')}
        >
          <Input id={`${id}-invalid`} aria-invalid defaultValue="0x12" />
        </Field>
        <Field htmlFor={`${id}-select`} label={t('Select')}>
          <Select
            id={`${id}-select`}
            value={asset}
            onValueChange={setAsset}
            options={[
              { value: 'usdc', label: 'USDC · TEST' },
              { value: 'eurc', label: 'EURC · TEST' },
            ]}
          />
        </Field>
        <Field htmlFor={`${id}-textarea`} label={t('Textarea')} optional>
          <Textarea id={`${id}-textarea`} rows={2} />
        </Field>
        <div className="flex flex-wrap items-center gap-6 text-base">
          <label className="flex items-center gap-2">
            <Checkbox defaultChecked /> {t('Checkbox')}
          </label>
          <label className="flex items-center gap-2">
            <Switch defaultChecked /> {t('Switch')}
          </label>
        </div>
        <RadioGroup value={option} onValueChange={setOption}>
          <RadioCard value="standard">
            <span className="font-medium">{t('Pay on the due date')}</span>
          </RadioCard>
          <RadioCard value="early">
            <span className="font-medium">{t('Pay early, 2% discount')}</span>
          </RadioCard>
        </RadioGroup>
      </Section>

      <Section title={t('Amounts and chain data')}>
        <Amount value="163000000000" size="xl" />
        <KeyValueList
          items={[
            { label: t('Inline'), value: <Amount value="875000000" /> },
            {
              label: t('Column'),
              value: <Amount value="875000000" context="column" />,
            },
            {
              label: t('Address'),
              value: (
                <Address address="0xa7518bb393b6d1b072a4bd875c173826f1405727" />
              ),
            },
            {
              label: t('Transaction'),
              value: (
                <TxHash hash="0xad546522f1b0c3e88aa18e0d3c5a8c2b7d9e1f00aa77bb66cc5544332211ef6e5" />
              ),
            },
          ]}
        />
        <BalanceMeter
          balance="4820000000"
          buffer="2000000000"
          target="6000000000"
        />
        <UsageBar
          label={t('Payments today')}
          used="2600000000"
          limit="10000000000"
        />
      </Section>

      <Section title={t('Decisions')}>
        <PolicyDecision
          validations={[
            {
              code: 'WITHIN_DAILY_LIMIT',
              decision: 'ALLOW',
              message: "Today's PAY total would be 3,543.80 of 10,000.00.",
            },
            {
              code: 'TARGET_NOT_REACHED',
              decision: 'WARN',
              message: 'O1 ends below its 6,000.00 target.',
            },
            {
              code: 'OVER_PER_REQUEST_LIMIT',
              decision: 'DENY',
              message: '3,200.00 is over the 2,000.00 per-request limit.',
            },
          ]}
        />
        <AiExplanation model="planner-v1">
          {t(
            'I scheduled Orbit Telecom early because its 2% discount expires tomorrow and the treasury has room.',
          )}
        </AiExplanation>
        <DiffView
          diff={[
            {
              field: 'Per-request limit',
              before: '2,000.00',
              after: '3,000.00',
              direction: 'LOOSER',
            },
            {
              field: 'Payments Safe buffer',
              before: '2,000.00',
              after: '2,500.00',
              direction: 'STRICTER',
            },
          ]}
        />
      </Section>

      <Section title={t('Feedback states')}>
        <Skeleton className="h-8 w-48" />
        <ListSkeleton rows={2} />
        <EmptyState
          icon={Inbox}
          title={t('Nothing to approve')}
          description={t('New requests appear here once they are submitted.')}
        />
        <ErrorState
          error={new Error('Network error')}
          onRetry={() => undefined}
        />
      </Section>
    </div>
  );
}

/**
 * Design review page (UI refactor plan, stage 0): every primitive in light
 * and dark side by side. Only reachable while the mock API is on.
 */
export function ComponentsPage() {
  return (
    <div className="min-h-dvh bg-background">
      <header className="border-b bg-surface px-6 py-4">
        <h1 className="text-2xl font-semibold">{t('Components')}</h1>
        <p className="mt-1 text-base text-muted-foreground">
          {t(
            'Every primitive in light and dark. Review token changes here before they reach a screen.',
          )}
        </p>
      </header>
      <div className="grid gap-6 p-6 xl:grid-cols-2">
        <section aria-label={t('Light theme')} className="light">
          <p className="mb-3 text-sm font-medium text-muted-foreground">
            {t('Light')}
          </p>
          <Gallery id="light" />
        </section>
        <section
          aria-label={t('Dark theme')}
          className="dark rounded-lg bg-background p-4 text-foreground"
        >
          <p className="mb-3 text-sm font-medium text-muted-foreground">
            {t('Dark')}
          </p>
          <Gallery id="dark" />
        </section>
      </div>
    </div>
  );
}
