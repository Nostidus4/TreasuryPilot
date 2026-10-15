import { CirclePause, CirclePlay, RotateCw } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { TxHash } from '@/components/domain/chain';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Field, Textarea } from '@/components/ui/input';
import { Alert } from '@/components/ui/misc';
import { useReviewItems } from '@/features/operations/api';
import { useOrgScope } from '@/features/orgs/org-scope';
import {
  usePauseTreasury,
  useResumeTx,
  useTreasury,
} from '@/features/treasury/api';
import { errorMessage } from '@/lib/api/http';
import type { Hex } from '@/lib/api/types';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';

/**
 * Pause is the emergency brake (F-026): one confirmation with a reason.
 * Resume is deliberately slower: it is a governance transaction.
 */
export function PauseDialog({
  onOpenChange,
  open,
  treasuryId,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
  treasuryId: string;
}) {
  const scope = useOrgScope();
  const pause = usePauseTreasury(scope.orgId, treasuryId);
  const [reason, setReason] = useState('');
  const [sentinelTx, setSentinelTx] = useState<Hex>();

  const close = (next: boolean) => {
    onOpenChange(next);
    if (!next) {
      setReason('');
      setSentinelTx(undefined);
      pause.reset();
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>{t('Pause this treasury?')}</DialogTitle>
          <DialogDescription>
            {t(
              'The agent stops sending transactions immediately, then the pause is written on-chain. Payments already sent to the network are not recalled.',
            )}
          </DialogDescription>
        </DialogHeader>
        {sentinelTx ? (
          <Alert tone="warning" title={t('Pausing…')}>
            {t('The backend is paused. The on-chain pause was sent:')}{' '}
            <TxHash hash={sentinelTx} />
          </Alert>
        ) : (
          <form
            id="pause-form"
            className="grid gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              pause.mutate(reason, {
                onSuccess: (result) => setSentinelTx(result.sentinelTxHash),
              });
            }}
          >
            <Field
              htmlFor="pause-reason"
              label={t('Reason')}
              hint={t('Recorded in the audit log and shown to every member.')}
              error={pause.isError ? errorMessage(pause.error) : undefined}
            >
              <Textarea
                id="pause-reason"
                required
                value={reason}
                aria-invalid={pause.isError}
                onChange={(event) => setReason(event.target.value)}
                placeholder={t(
                  'e.g. Suspicious payee change on invoice NSA-2026-288',
                )}
              />
            </Field>
          </form>
        )}
        <DialogFooter>
          <Button onClick={() => close(false)}>
            {sentinelTx ? t('Close') : t('Keep operating')}
          </Button>
          {!sentinelTx && (
            <Button
              type="submit"
              form="pause-form"
              variant="danger"
              loading={pause.isPending}
              disabled={!reason.trim()}
            >
              <CirclePause aria-hidden="true" />
              {t('Pause treasury')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Banners that must stay visible on every page until the state clears. */
export function StatusBanners() {
  const scope = useOrgScope();
  const navigate = useNavigate();
  const treasury = useTreasury(scope.orgId, scope.treasuryId);
  const review = useReviewItems(scope.orgId);
  const resume = useResumeTx(scope.orgId, scope.treasuryId ?? '');
  const state = treasury.data;
  if (!state) return null;
  const { status, pauseReason } = state.treasury;
  const outflows = (review.data?.items ?? []).filter(
    (item) => item.type === 'UNEXPECTED_OUTFLOW' && item.status === 'Open',
  );

  const startResume = () =>
    resume.mutate(undefined, {
      onSuccess: ({ governanceTx }) =>
        navigate(`${scope.base}/governance/${governanceTx.id}`),
      onError: (error) => toast.error(errorMessage(error)),
    });

  return (
    <div className="grid gap-px">
      {state.mandate?.status === 'Expired' && (
        <Alert
          tone="danger"
          className="rounded-none border-x-0 border-t-0 px-4 sm:px-6"
          title={t('Mandate expired')}
          action={
            scope.can('OWN') && (
              <Button asChild size="sm">
                <Link to={`${scope.tBase}/mandate`}>{t('Review mandate')}</Link>
              </Button>
            )
          }
        >
          {t(
            'The agent cannot run new plans until an Owner activates a current mandate.',
          )}
        </Alert>
      )}
      {status === 'PauseRequested' && (
        <Alert
          tone="warning"
          className="rounded-none border-x-0 border-t-0 px-4 sm:px-6"
          title={t('Pausing…')}
        >
          {t(
            'The agent has stopped. Waiting for the on-chain pause to confirm.',
          )}
        </Alert>
      )}
      {status === 'Paused' && (
        <Alert
          tone="danger"
          className="rounded-none border-x-0 border-t-0 px-4 sm:px-6"
          title={t('Paused on-chain')}
          action={
            scope.can('OWN') && (
              <Button
                size="sm"
                loading={resume.isPending}
                onClick={startResume}
              >
                <CirclePlay aria-hidden="true" />
                {t('Resume…')}
              </Button>
            )
          }
        >
          {t('No plan can run and the module rejects every payment.')}
          {pauseReason && ` ${t('Reason')}: ${pauseReason}`}
          {!scope.can('OWN') &&
            ` ${t('Only Safe owners can resume, through a governance transaction.')}`}
        </Alert>
      )}
      {state.coverage.status === 'PARTIAL' && state.coverage.acknowledged && (
        <Alert
          tone="warning"
          className="rounded-none border-x-0 border-t-0 px-4 sm:px-6"
          title={t('Protected mode off — another module can move funds')}
        >
          {state.coverage.details[0]}
        </Alert>
      )}
      {outflows.length > 0 && (
        <Alert
          tone="danger"
          className="rounded-none border-x-0 border-t-0 px-4 sm:px-6"
          title={t('Unexpected outflow')}
          action={
            <Button asChild size="sm">
              <Link to={`${scope.base}/review`}>{t('Review')}</Link>
            </Button>
          }
        >
          {outflows[0].detail}
          {outflows.length > 1 &&
            ` ${t('{{count}} more in the review queue.', { count: outflows.length - 1 })}`}
        </Alert>
      )}
      {state.staleness.stale && (
        <Alert
          tone="warning"
          className="rounded-none border-x-0 border-t-0 px-4 sm:px-6"
          title={t('Balances may be out of date')}
          action={
            <Button size="sm" onClick={() => void treasury.refetch()}>
              <RotateCw aria-hidden="true" />
              {t('Refresh')}
            </Button>
          }
        >
          {t('Last chain snapshot: {{when}} (block {{block}}).', {
            when: formatRelative(state.staleness.observedAt),
            block: state.staleness.blockNumber,
          })}{' '}
          {t('No plan runs on a stale snapshot.')}
        </Alert>
      )}
    </div>
  );
}
