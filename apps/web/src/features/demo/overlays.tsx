import { ArrowDown, ArrowRight } from 'lucide-react';
import type { ReactNode } from 'react';

import { Badge } from '@/components/ui/badge';
import { t } from '@/lib/i18n';

import { useScenario } from './api';
import { DEMO_BANNER_HEIGHT } from './banner';

function Box({
  children,
  tone = 'plain',
  title,
}: {
  children?: ReactNode;
  tone?: 'plain' | 'ai' | 'engine' | 'policy';
  title: string;
}) {
  const color =
    tone === 'ai'
      ? 'border-ai-border bg-ai-muted'
      : tone === 'engine'
        ? 'border-info-border bg-info-muted'
        : tone === 'policy'
          ? 'border-success-border bg-success-muted'
          : 'border-border-strong bg-surface';
  return (
    <div className={`rounded-lg border px-4 py-3 text-center ${color}`}>
      <p className="text-base font-semibold">{title}</p>
      {children && (
        <p className="mt-0.5 text-sm text-muted-foreground">{children}</p>
      )}
    </div>
  );
}

const Arrow = ({ down }: { down?: boolean }) =>
  down ? (
    <ArrowDown
      className="mx-auto size-5 text-subtle-foreground"
      aria-hidden="true"
    />
  ) : (
    <ArrowRight
      className="size-5 shrink-0 text-subtle-foreground"
      aria-hidden="true"
    />
  );

/** Scene 10: the architecture diagram from the runbook. */
function AgentDiagram() {
  return (
    <div
      data-testid="overlay-agent"
      className="mx-auto grid w-full max-w-5xl gap-5 px-6"
    >
      <h1 className="text-center text-3xl font-semibold">
        {t('How the agent works')}
      </h1>
      <div className="grid items-center gap-3 sm:grid-cols-[1fr_auto_1fr_auto_1fr]">
        <Box title={t('Reviewed invoice')}>{t('Human-verified fields')}</Box>
        <Arrow />
        <Box title={t('Approved obligations')}>
          {t('Payroll, upcoming bills')}
        </Box>
        <Arrow />
        <Box title={t('Observations')}>{t('Balances, pool, gas')}</Box>
      </div>
      <Arrow down />
      <div className="rounded-lg border-2 border-primary px-4 py-4">
        <p className="mb-3 text-center text-lg font-semibold">{t('Agent')}</p>
        <div className="grid items-center gap-3 sm:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">
          <Box title={t('Observe')} />
          <Arrow />
          <Box title={t('Plan')} />
          <Arrow />
          <Box title={t('Act')} />
          <Arrow />
          <Box title={t('Verify')} />
        </div>
      </div>
      <Arrow down />
      <div className="grid gap-3 sm:grid-cols-3">
        <Box title={t('AI draft / explain')} tone="ai">
          {t('Text only: never moves money')}
        </Box>
        <Box title={t('Financial engine')} tone="engine">
          {t('Deterministic amounts')}
        </Box>
        <Box title={t('Policy checks')} tone="policy">
          {t('Mandate, payees, limits')}
        </Box>
      </div>
      <Arrow down />
      <div className="grid items-center gap-3 sm:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">
        <Box title={t('Signer')} />
        <Arrow />
        <Box title={t('Safe / module')} />
        <Arrow />
        <Box title={t('Pool / recipient')} />
        <Arrow />
        <Box title={t('Verify / reconcile')} />
      </div>
    </div>
  );
}

/** Scene 11: the four outcome lines, computed from the S5 state. */
function OutcomeFrame({ lines, footer }: { lines: string[]; footer: string }) {
  return (
    <div
      data-testid="overlay-outcome"
      className="mx-auto grid w-full max-w-3xl gap-8 px-6"
    >
      <h1 className="text-center text-3xl font-semibold">{t('Outcome')}</h1>
      <ul className="grid gap-4">
        {lines.map((line) => (
          <li
            key={line}
            className="rounded-lg border bg-surface px-5 py-4 text-xl"
          >
            {line}
          </li>
        ))}
      </ul>
      <p className="text-center text-base text-muted-foreground">{footer}</p>
    </div>
  );
}

/** Full-window frames for scenes 10 and 11; only the Director shows or hides them. */
export function DemoOverlays() {
  const scenario = useScenario();
  const view = scenario.data;
  const overlay = view?.state.director.overlay ?? 'NONE';
  if (!view || overlay === 'NONE') return null;
  return (
    <div
      role="dialog"
      aria-label={overlay === 'AGENT' ? t('How the agent works') : t('Outcome')}
      style={{ paddingTop: DEMO_BANNER_HEIGHT }}
      className="fixed inset-0 z-[60] grid place-items-center overflow-y-auto bg-background"
    >
      <div className="py-12">
        {overlay === 'AGENT' ? (
          <AgentDiagram />
        ) : (
          <OutcomeFrame
            lines={view.outcome.lines}
            footer={view.outcome.footer}
          />
        )}
        <p className="mt-8 text-center">
          <Badge tone="warning">{t('SIMULATION / SYNTHETIC DATA')}</Badge>
        </p>
      </div>
    </div>
  );
}
