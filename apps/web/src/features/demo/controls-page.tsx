import { useState } from 'react';

import { KeyValueList } from '@/components/domain/display';
import { ListSkeleton } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/controls';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Alert } from '@/components/ui/misc';
import { t } from '@/lib/i18n';

import { actionError, useDemoAction, useScenario } from './api';
import { fmt, roleNames, utc, utcSeconds } from './format';
import { Usdc } from './usdc';
import type { AgentStatus } from './types';

const agentLabel: Record<AgentStatus, string> = {
  ACTIVE: 'Active',
  PAUSING: 'Pausing',
  PAUSED: 'Paused',
};

function capItem({
  label,
  tx,
  day,
}: {
  label: string;
  tx: string;
  day: string;
}) {
  return {
    label,
    value: (
      <span className="num">
        {fmt(tx)} {t('per transaction')} · {fmt(day)} {t('per day')} USDC
      </span>
    ),
  };
}

export function DemoControlsPage() {
  const { data } = useScenario();
  const pause = useDemoAction('/demo/agent/pause');
  const [confirming, setConfirming] = useState(false);
  if (!data) {
    return (
      <Page title={t('Controls')}>
        <ListSkeleton />
      </Page>
    );
  }
  const { state, fixture } = data;
  const m = fixture.mandate;
  const owner = state.role === 'OWNER';
  const caps = [
    { label: 'PAY', tx: m.payPerTx, day: m.payDaily },
    { label: 'REFILL', tx: m.refillPerTx, day: m.refillDaily },
    { label: 'WITHDRAW', tx: m.withdrawPerTx, day: m.withdrawDaily },
    { label: 'SUPPLY', tx: m.supplyPerTx, day: m.supplyDaily },
  ];
  return (
    <Page
      title={t('Controls')}
      description={t(
        'The rules the agent can never exceed, and its on/off switch',
      )}
    >
      <Tabs defaultValue="mandate">
        <TabsList className="mb-4">
          <TabsTrigger value="mandate">{t('Mandate')}</TabsTrigger>
          <TabsTrigger value="agent">{t('Agent controls')}</TabsTrigger>
        </TabsList>

        <TabsContent value="mandate" data-testid="mandate-summary">
          <Card>
            <CardHeader
              title={`${t('Mandate')} v${m.version}`}
              description={`${t('Expires')} ${utc(m.expiresAt)}`}
              action={
                <Badge tone="success">
                  {t(m.status === 'ACTIVE' ? 'Active' : m.status)}
                </Badge>
              }
            />
            <CardContent>
              <KeyValueList
                items={[
                  {
                    label: t('Allowed actions'),
                    value: (
                      <span className="flex flex-wrap justify-end gap-1">
                        {m.allowedActions.map((action) => (
                          <Badge key={action} tone="outline">
                            {action}
                          </Badge>
                        ))}
                      </span>
                    ),
                  },
                  ...caps.map(capItem),
                  {
                    label: t('Pool exposure cap'),
                    value: <Usdc value={m.maxPoolExposure} />,
                  },
                  { label: t('Allowed pool'), value: fixture.pool.name },
                  {
                    label: t('Allowed payees'),
                    value: (
                      <span className="flex flex-col items-end">
                        {fixture.payees.map((payee) => (
                          <span key={payee.id}>
                            {payee.name}{' '}
                            <Badge tone="success">{t('Active')}</Badge>
                          </span>
                        ))}
                      </span>
                    ),
                  },
                  {
                    label: t('Unknown payee'),
                    value: (
                      <Badge tone="danger">{m.unknownRecipientPolicy}</Badge>
                    ),
                  },
                  {
                    label: t('Borrow'),
                    value: t('Requires separate authorization'),
                    hint: t('Not executed in this scenario'),
                  },
                  {
                    label: t('Reserve horizon'),
                    value: `${m.reserveHorizonDays} ${t('days')}`,
                  },
                  {
                    label: t('Withdraw margin'),
                    value: `${m.withdrawMarginBps / 100}%`,
                  },
                ]}
              />
              <p className="mt-4 text-sm text-muted-foreground">
                {t(
                  'Mandate changes need governance signatures. This role has no edit action here.',
                )}
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="agent">
          <Card>
            <CardHeader
              title={t('Agent')}
              description={t(
                'Observes, plans and acts only inside the mandate',
              )}
              action={
                <Badge
                  data-testid="agent-status"
                  tone={
                    state.agent.status === 'ACTIVE'
                      ? 'success'
                      : state.agent.status === 'PAUSING'
                        ? 'warning'
                        : 'danger'
                  }
                >
                  {t(agentLabel[state.agent.status])}
                </Badge>
              }
            />
            <CardContent className="grid gap-4">
              {owner ? (
                <div>
                  <Button
                    variant="danger-outline"
                    data-testid="agent-pause"
                    disabled={state.agent.status !== 'ACTIVE'}
                    onClick={() => setConfirming(true)}
                  >
                    {t('Pause agent')}
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t('Only the Owner can pause the agent.')} (
                  {roleNames[state.role].name} · {roleNames[state.role].title})
                </p>
              )}
              {pause.isError && (
                <Alert tone="danger">{actionError(pause.error)}</Alert>
              )}
              <div>
                <h3 className="mb-2 text-base font-semibold">
                  {t('Activity')}
                </h3>
                {state.activity.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {t('No agent activity yet.')}
                  </p>
                ) : (
                  <ul
                    className="divide-y rounded-md border"
                    data-testid="agent-activity"
                  >
                    {state.activity.map((entry) => (
                      <li
                        key={entry.id}
                        className="flex justify-between gap-4 px-3 py-2 text-base"
                      >
                        <span>{entry.text}</span>
                        <span className="num text-sm text-muted-foreground">
                          {utcSeconds(entry.at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent size="sm">
          <DialogHeader>
            <DialogTitle>{t('Pause the agent?')}</DialogTitle>
            <DialogDescription>
              {t(
                'The agent stops starting new actions. Balances and reserves are not changed.',
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setConfirming(false)}>
              {t('Cancel')}
            </Button>
            <Button
              variant="danger"
              data-testid="agent-pause-confirm"
              loading={pause.isPending}
              onClick={() =>
                pause.mutate(undefined, {
                  onSettled: () => setConfirming(false),
                })
              }
            >
              {t('Confirm pause')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Page>
  );
}
