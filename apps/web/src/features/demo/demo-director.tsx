import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Switch } from '@/components/ui/controls';

import { utc } from './demo-kit';
import {
  CHECKPOINTS,
  dispatch,
  guard,
  loadCheckpoint,
  resetDayD,
  usd,
  useScenario,
  type Event,
} from './scenario';

/**
 * Director panel (runbook §4.3): off-record playback controls in a separate
 * window. It never signs or broadcasts; it only advances the simulation.
 */
export function DirectorPage() {
  const s = useScenario();
  const [message, setMessage] = useState<string | null>(null);
  const controls: Array<{ label: string; scene: string; event: Event }> = [
    {
      label: 'RELEASE_EXECUTION_WINDOW',
      scene: 'Scene 6 · after the plan is explained',
      event: { type: 'RELEASE_EXECUTION_WINDOW' },
    },
    {
      label: 'RELEASE_PAY_VERIFICATION',
      scene: 'Scene 6 · after 8–12 s of UNKNOWN',
      event: { type: 'RELEASE_PAY_VERIFICATION' },
    },
    {
      label: 'LOAD_DAY_D_PLUS_ONE',
      scene: 'Scene 8 · after the D+1 transition card',
      event: { type: 'LOAD_DAY_D_PLUS_ONE' },
    },
    {
      label: 'RELEASE_SURPLUS_CYCLE',
      scene: 'Scene 8 · after View allocation',
      event: { type: 'RELEASE_SURPLUS_CYCLE' },
    },
    {
      label: 'LOAD_SECURITY_INBOX',
      scene: 'Before scene 9',
      event: { type: 'LOAD_SECURITY_INBOX' },
    },
  ];
  const run = (event: Event) =>
    setMessage(dispatch(event) ?? `${event.type} applied.`);
  const b = s.balances;
  return (
    <div className="mx-auto grid max-w-3xl gap-4 p-6">
      <div>
        <h1 className="text-xl font-semibold">Director panel · off record</h1>
        <p className="text-sm text-muted-foreground">
          Simulation playback only. Keep this window out of the recording. Open{' '}
          <a
            className="text-primary underline"
            href="/demo"
            target="_blank"
            rel="noreferrer"
          >
            /demo
          </a>{' '}
          in the recording window.
        </p>
      </div>
      <Card>
        <CardHeader
          title="State"
          description={`runId ${s.runId} · ${utc(s.clock)}`}
        />
        <CardContent className="num grid gap-1 text-sm">
          <p>
            T {usd(b.t)} · O1 {usd(b.o1)} · O2 {usd(b.o2)} · Aave {usd(b.aave)}
          </p>
          <p>
            A: {s.a.status} · steps {s.a.steps.withdraw}/{s.a.steps.refill}/
            {s.a.steps.pay} · recon {s.a.recon} · submissions{' '}
            {s.a.paySubmissions}
          </p>
          <p>
            D+1 {String(s.dayPlusOne)} · supply {s.supply} · security{' '}
            {s.security.loaded
              ? s.security.blocked
                ? 'blocked'
                : 'loaded'
              : '—'}{' '}
            · agent {s.agent} · role {s.role}
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader title="Playback" />
        <CardContent className="grid gap-2">
          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <p className="font-mono text-sm font-semibold">RESET_DAY_D</p>
              <p className="text-xs text-muted-foreground">
                Before each take: S0, Linh, A/C/X absent
              </p>
            </div>
            <Button
              variant="danger"
              onClick={() => {
                resetDayD();
                setMessage('Reset to Day D (S0).');
              }}
            >
              Reset
            </Button>
          </div>
          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <p className="font-mono text-sm font-semibold">
                HOLD_PAY_UNKNOWN
              </p>
              <p className="text-xs text-muted-foreground">
                On: stay at Outcome unknown until released. Off: auto-verify
                after 10 s.
              </p>
            </div>
            <Switch
              checked={s.holdUnknown}
              onCheckedChange={(value) =>
                dispatch({ type: 'SET_HOLD_UNKNOWN', value })
              }
            />
          </div>
          {controls.map((control) => {
            const blocked = guard(s, control.event);
            return (
              <div
                key={control.label}
                className="flex items-center justify-between gap-3 rounded-md border p-3"
              >
                <div>
                  <p className="font-mono text-sm font-semibold">
                    {control.label}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {control.scene}
                    {blocked ? ` · ${blocked}` : ''}
                  </p>
                </div>
                <Button
                  variant="primary"
                  disabled={!!blocked}
                  onClick={() => run(control.event)}
                >
                  Run
                </Button>
              </div>
            );
          })}
          {message && (
            <p className="text-sm text-muted-foreground">{message}</p>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader
          title="Checkpoints"
          description="Replays the same events from S0 with a new runId. Simulator only, not a chain rollback."
        />
        <CardContent className="grid gap-2">
          {CHECKPOINTS.map((checkpoint) => (
            <Button
              key={checkpoint.id}
              className="justify-start"
              onClick={() => {
                loadCheckpoint(checkpoint.events);
                setMessage(`Loaded ${checkpoint.label}.`);
              }}
            >
              {checkpoint.label}
            </Button>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader title="Overlays" description="Scenes 10–11" />
        <CardContent className="flex gap-2 text-sm">
          <a
            className="text-primary underline"
            href="/demo/architecture"
            target="_blank"
            rel="noreferrer"
          >
            Architecture
          </a>
          <a
            className="text-primary underline"
            href="/demo/outcome"
            target="_blank"
            rel="noreferrer"
          >
            Outcome
          </a>
        </CardContent>
      </Card>
    </div>
  );
}
