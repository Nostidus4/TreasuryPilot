import { useMutation, useQueryClient } from '@tanstack/react-query';
import { EyeOff } from 'lucide-react';
import { useState } from 'react';

import { KeyValueList } from '@/components/domain/display';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Alert } from '@/components/ui/misc';
import { api, errorMessage } from '@/lib/api/http';
import { exitDemoScenario } from '@/lib/env';
import { t } from '@/lib/i18n';

import { demoKey, useDemoSync, useScenario } from './api';
import { utcSeconds } from './format';
import type { ScenarioView } from './types';

type Action =
  | 'RESET_DAY_D'
  | 'RELEASE_EXECUTION_WINDOW'
  | 'HOLD_PAY_UNKNOWN'
  | 'RELEASE_PAY_VERIFICATION'
  | 'LOAD_DAY_D_PLUS_ONE'
  | 'RELEASE_SURPLUS_CYCLE'
  | 'LOAD_SECURITY_INBOX'
  | 'SHOW_AGENT_OVERLAY'
  | 'SHOW_OUTCOME_OVERLAY'
  | 'HIDE_OVERLAY';

interface Control {
  action: Action;
  scene: string;
  hint: string;
}

const SCENE_CONTROLS: Control[] = [
  {
    action: 'RELEASE_EXECUTION_WINDOW',
    scene: 'Scene 6',
    hint: 'Opens the approved window (10:05 UTC). The agent starts by itself.',
  },
  {
    action: 'HOLD_PAY_UNKNOWN',
    scene: 'Scene 6',
    hint: 'Keeps PAY at "Outcome unknown" (on by default).',
  },
  {
    action: 'RELEASE_PAY_VERIFICATION',
    scene: 'Scene 6',
    hint: 'Verifies the same SIM-TX-PAY-001 once. Wait 8-12 s at Outcome unknown first.',
  },
  {
    action: 'LOAD_DAY_D_PLUS_ONE',
    scene: 'Scene 8',
    hint: 'Next day: revenue and approved C land together.',
  },
  {
    action: 'RELEASE_SURPLUS_CYCLE',
    scene: 'Scene 8',
    hint: 'Run after "View allocation". Supplies the surplus.',
  },
  {
    action: 'LOAD_SECURITY_INBOX',
    scene: 'Scene 9',
    hint: 'Adds INV-CLOUD-043. No ledger or reserve change.',
  },
];

const OVERLAY_CONTROLS: Control[] = [
  {
    action: 'SHOW_AGENT_OVERLAY',
    scene: 'Scene 10',
    hint: '"How the agent works" in the main window.',
  },
  {
    action: 'SHOW_OUTCOME_OVERLAY',
    scene: 'Scene 11',
    hint: 'Outcome frame computed from S5.',
  },
  { action: 'HIDE_OVERLAY', scene: '', hint: 'Back to the product screens.' },
];

function suggestNext(view: ScenarioView): Action | null {
  const { state } = view;
  const a = state.invoiceA;
  if (a.status === 'READY_WAITING_WINDOW') return 'RELEASE_EXECUTION_WINDOW';
  if (a.status === 'OUTCOME_UNKNOWN') return 'RELEASE_PAY_VERIFICATION';
  if (
    a.status === 'PAID' &&
    a.recon === 'MATCHED' &&
    !state.director.dayPlusOne
  )
    return 'LOAD_DAY_D_PLUS_ONE';
  if (state.director.dayPlusOne && state.supply.status === 'NOT_READY')
    return 'RELEASE_SURPLUS_CYCLE';
  if (state.supply.status === 'CONFIRMED' && !state.director.securityLoaded)
    return 'LOAD_SECURITY_INBOX';
  return null;
}

/**
 * Off-record control room. Open it in its own browser window (`/demo/director`); it drives the
 * main window over BroadcastChannel and shared storage. Never put this window in the recording.
 */
export function DirectorPage() {
  useDemoSync();
  const queryClient = useQueryClient();
  const scenario = useScenario();
  const [message, setMessage] = useState<{
    tone: 'success' | 'info' | 'danger';
    text: string;
  } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  const run = useMutation({
    mutationFn: (action: Action) =>
      api.post<ScenarioView & { noop: boolean; message: string }>(
        `/demo/director/${action}`,
        {},
      ),
    onSuccess: (result, action) => {
      setMessage({
        tone: result.noop ? 'info' : 'success',
        text: `${action}: ${result.message || 'done'}`,
      });
    },
    onError: (error, action) =>
      setMessage({ tone: 'danger', text: `${action}: ${errorMessage(error)}` }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: demoKey }),
  });

  const view = scenario.data;
  const next = view ? suggestNext(view) : null;
  const envLocked = import.meta.env.VITE_DEMO_SCENARIO === 'TP-DEMO-7M30-01';

  const button = (control: Control) => (
    <div
      key={control.action}
      className="flex items-center justify-between gap-3 rounded-md border p-3"
    >
      <div className="min-w-0">
        <p className="font-mono text-sm font-medium">
          {control.action}{' '}
          {control.scene && <Badge tone="neutral">{control.scene}</Badge>}
          {next === control.action && (
            <Badge tone="success" className="ml-1">
              {t('Next')}
            </Badge>
          )}
        </p>
        <p className="text-sm text-muted-foreground">{control.hint}</p>
      </div>
      <Button
        size="sm"
        variant={next === control.action ? 'primary' : 'secondary'}
        data-testid={`director-${control.action}`}
        disabled={run.isPending}
        onClick={() => run.mutate(control.action)}
      >
        {t('Run')}
      </Button>
    </div>
  );

  return (
    <main
      className="mx-auto grid max-w-4xl gap-4 px-4 py-6"
      data-testid="director-panel"
    >
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{t('Director panel')}</h1>
        <Badge tone="danger">
          <EyeOff aria-hidden="true" />{' '}
          {t('Off-record: keep out of the recording')}
        </Badge>
        <Badge tone="warning" className="ml-auto">
          {t('SIMULATION / SYNTHETIC DATA')}
        </Badge>
      </header>

      {message && (
        <Alert tone={message.tone} data-testid="director-message">
          {message.text}
        </Alert>
      )}

      <Card>
        <CardHeader
          title={t('Current state')}
          description={t('Read from the shared snapshot')}
        />
        <CardContent>
          {view ? (
            <KeyValueList
              items={[
                {
                  label: t('Ledger stage'),
                  value: (
                    <Badge tone="info" data-testid="director-stage">
                      {view.stage ?? '—'}
                    </Badge>
                  ),
                },
                {
                  label: t('Invoice A'),
                  value: (
                    <span data-testid="director-invoice">
                      {view.state.invoiceA.status}
                    </span>
                  ),
                },
                { label: t('Execution'), value: view.state.invoiceA.execution },
                {
                  label: t('Reconciliation'),
                  value: view.state.invoiceA.recon,
                },
                {
                  label: t('PAY submissions / payments'),
                  value: `${view.state.invoiceA.paySubmissions} / ${view.state.invoiceA.paymentCount}`,
                },
                { label: t('Supply cycle'), value: view.state.supply.status },
                { label: t('Agent'), value: view.state.agent.status },
                {
                  label: t('INV-CLOUD-043'),
                  value: view.state.invoiceX.status,
                },
                {
                  label: t('Hold at Outcome unknown'),
                  value: view.state.director.holdPayUnknown
                    ? t('ON')
                    : t('OFF'),
                },
                { label: t('Overlay'), value: view.state.director.overlay },
                { label: t('Main window role'), value: view.state.role },
                {
                  label: t('Run ID'),
                  value: (
                    <span data-testid="director-run">{view.state.runId}</span>
                  ),
                },
                {
                  label: t('Scenario time'),
                  value: utcSeconds(view.state.clock),
                },
              ]}
            />
          ) : (
            <p className="text-muted-foreground">{t('Loading…')}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title={t('Take controls')}
          description={t(
            'Each control is idempotent and refuses to run out of order.',
          )}
        />
        <CardContent className="grid gap-2">
          <div className="flex items-center justify-between gap-3 rounded-md border border-danger-border p-3">
            <div>
              <p className="font-mono text-sm font-medium">
                RESET_DAY_D{' '}
                <Badge tone="neutral">{t('Before each take')}</Badge>
              </p>
              <p className="text-sm text-muted-foreground">
                {t(
                  'Back to S0 with Linh. Clears events, references, holds and counters; starts a new run.',
                )}
              </p>
            </div>
            {confirmReset ? (
              <Button
                size="sm"
                variant="danger"
                data-testid="director-RESET_DAY_D"
                onClick={() => {
                  setConfirmReset(false);
                  run.mutate('RESET_DAY_D');
                }}
              >
                {t('Confirm reset')}
              </Button>
            ) : (
              <Button
                size="sm"
                variant="danger-outline"
                onClick={() => setConfirmReset(true)}
              >
                {t('Reset')}
              </Button>
            )}
          </div>
          {SCENE_CONTROLS.map(button)}
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title={t('Overlays')}
          description={t('Scenes 10 and 11, shown over the main window')}
        />
        <CardContent className="grid gap-2">
          {OVERLAY_CONTROLS.map(button)}
        </CardContent>
      </Card>

      {!envLocked && (
        <p className="text-sm text-muted-foreground">
          <Button
            variant="link"
            onClick={() => {
              exitDemoScenario();
              window.location.assign(import.meta.env.BASE_URL);
            }}
          >
            {t('Exit demo')}
          </Button>{' '}
          {t('and return to the default mock app.')}
        </p>
      )}
    </main>
  );
}
