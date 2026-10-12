import {
  Check,
  PenLine,
  TriangleAlert,
  Wallet as WalletIcon,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { toast } from 'sonner';

import { Address } from '@/components/domain/chain';
import { Badge } from '@/components/ui/badge';
import { Button, type ButtonProps } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Alert, Avatar } from '@/components/ui/misc';
import { useChain } from '@/lib/api/chains';
import { errorMessage } from '@/lib/api/http';
import type {
  DecodedCall,
  GovernanceTx,
  Hex,
  TypedData,
} from '@/lib/api/types';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { isUserRejection, useWallet } from '@/lib/wallet/wallet-context';
import { cn } from '@/lib/utils';

/**
 * Renders exactly the object that goes to `signTypedData` (M16-D1): the rows
 * are derived from `typedData.types[primaryType]` and `typedData.message`,
 * with no relabelling or reformatting of values.
 */
export function TypedDataTable({ typedData }: { typedData: TypedData }) {
  const fields = typedData.types[typedData.primaryType] ?? [];
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-surface-muted px-3 py-2">
        <p className="text-sm font-medium">
          {typedData.primaryType}{' '}
          <span className="font-normal text-muted-foreground">
            · {t('{{count}} fields', { count: fields.length })}
          </span>
        </p>
        <p className="num text-xs text-muted-foreground">
          {typedData.domain.name ? `${typedData.domain.name} · ` : ''}
          chainId {typedData.domain.chainId}
        </p>
      </div>
      <dl className="divide-y text-sm">
        {fields.map((field) => (
          <div
            key={field.name}
            className="grid gap-x-3 px-3 py-1.5 sm:grid-cols-[10rem_1fr]"
          >
            <dt className="text-muted-foreground">
              {field.name}{' '}
              <span className="num text-xs text-subtle-foreground">
                {field.type}
              </span>
            </dt>
            <dd className="num break-all">
              {String(typedData.message[field.name])}
            </dd>
          </div>
        ))}
        <div className="grid gap-x-3 bg-surface-muted px-3 py-1.5 sm:grid-cols-[10rem_1fr]">
          <dt className="text-muted-foreground">verifyingContract</dt>
          <dd className="num break-all">
            {typedData.domain.verifyingContract}
          </dd>
        </div>
      </dl>
    </div>
  );
}

export function ConnectWalletDialog({
  onOpenChange,
  open,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const wallet = useWallet();
  const [error, setError] = useState('');
  const connect = (kind: 'injected' | 'demo') => {
    setError('');
    wallet
      .connect(kind)
      .then(() => onOpenChange(false))
      .catch((cause: unknown) =>
        setError(
          isUserRejection(cause)
            ? t('The connection request was rejected in your wallet.')
            : errorMessage(cause),
        ),
      );
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>{t('Connect a wallet')}</DialogTitle>
          <DialogDescription>
            {t(
              'Your wallet signs approvals and governance transactions. TreasuryPilot never holds your keys.',
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-2">
          <Button
            size="lg"
            className="justify-start"
            disabled={!wallet.hasInjected}
            loading={wallet.connecting}
            onClick={() => connect('injected')}
          >
            <WalletIcon aria-hidden="true" />
            {wallet.hasInjected
              ? t('Browser wallet')
              : t('No browser wallet detected')}
          </Button>
          {wallet.demoAvailable && (
            <Button
              size="lg"
              className="justify-start"
              onClick={() => connect('demo')}
            >
              <PenLine aria-hidden="true" />
              {t('Demo signer')}
              <Badge tone="warning" className="ml-auto">
                {t('Mock API only')}
              </Badge>
            </Button>
          )}
        </div>
        {wallet.demoAvailable && (
          <p className="text-xs text-muted-foreground">
            {t(
              'The demo signer is a public Anvil test key. It produces real EIP-712 signatures and is available only while the app runs on the mock API.',
            )}
          </p>
        )}
        {error && <Alert tone="danger">{error}</Alert>}
      </DialogContent>
    </Dialog>
  );
}

/**
 * Guards every wallet action: connected, on the right network (M16-D9), and
 * not blocked by a business rule. A wallet rejection changes nothing and
 * shows a toast (spec §6).
 */
export function WalletActionButton({
  action,
  blockedReason,
  chainId,
  children,
  requiredAddresses,
  ...buttonProps
}: Omit<ButtonProps, 'onClick'> & {
  action: () => Promise<void>;
  /** Why the action is not available yet, shown under the button. */
  blockedReason?: string;
  chainId: number;
  /** If set, the connected wallet must be one of these. */
  requiredAddresses?: { addresses: Hex[]; message: string };
}) {
  const wallet = useWallet();
  const chain = useChain(chainId);
  const [busy, setBusy] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);

  const run = (task: () => Promise<void>) => {
    setBusy(true);
    task()
      .catch((error: unknown) => {
        if (isUserRejection(error)) {
          toast.info(t('Rejected in your wallet'), {
            description: t('Nothing was signed or sent. No state changed.'),
          });
        } else {
          toast.error(errorMessage(error));
        }
      })
      .finally(() => setBusy(false));
  };

  if (!wallet.address) {
    return (
      <div className="grid gap-1.5">
        <Button
          {...buttonProps}
          variant="secondary"
          onClick={() => setConnectOpen(true)}
        >
          <WalletIcon aria-hidden="true" />
          {t('Connect wallet to continue')}
        </Button>
        <ConnectWalletDialog open={connectOpen} onOpenChange={setConnectOpen} />
      </div>
    );
  }

  if (wallet.chainId !== chainId) {
    return (
      <Alert
        tone="warning"
        title={t('Wrong network')}
        action={
          <Button
            size="sm"
            loading={busy}
            onClick={() => run(() => wallet.switchChain(chainId))}
          >
            {t('Switch to {{name}}', { name: chain?.name ?? String(chainId) })}
          </Button>
        }
      >
        {t(
          'Your wallet is on a different network. Signing is blocked until you switch.',
        )}
      </Alert>
    );
  }

  const wrongWallet =
    requiredAddresses &&
    !requiredAddresses.addresses.some(
      (address) => address.toLowerCase() === wallet.address!.toLowerCase(),
    )
      ? requiredAddresses.message
      : undefined;
  const reason = blockedReason ?? wrongWallet;

  return (
    <div className="grid gap-1.5">
      <Button
        {...buttonProps}
        loading={busy}
        disabled={Boolean(reason) || buttonProps.disabled}
        aria-describedby={reason ? 'wallet-action-reason' : undefined}
        onClick={() => run(action)}
      >
        {children}
      </Button>
      {reason && (
        <p
          id="wallet-action-reason"
          className="flex items-start gap-1.5 text-sm text-warning-foreground"
        >
          <TriangleAlert
            className="mt-0.5 size-3.5 shrink-0"
            aria-hidden="true"
          />
          {reason}
        </p>
      )}
    </div>
  );
}

/** Who has signed a Safe transaction, against its threshold. */
export function SignatureProgress({
  tx,
}: {
  tx: Pick<GovernanceTx, 'owners' | 'signatures' | 'threshold'>;
}) {
  const signedCount = tx.signatures.length;
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">
          {t('{{signed}} of {{threshold}} signatures', {
            signed: signedCount,
            threshold: tx.threshold,
          })}
        </p>
        <div
          className="flex gap-1"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={tx.threshold}
          aria-valuenow={Math.min(signedCount, tx.threshold)}
          aria-label={t('Signatures collected')}
        >
          {Array.from({ length: tx.threshold }, (_, index) => (
            <span
              key={index}
              className={cn(
                'h-1.5 w-8 rounded-full',
                index < signedCount ? 'bg-success' : 'bg-border-strong',
              )}
            />
          ))}
        </div>
      </div>
      <ul className="grid gap-1.5">
        {tx.owners.map((owner) => {
          const signature = tx.signatures.find(
            (item) => item.owner.toLowerCase() === owner.address.toLowerCase(),
          );
          return (
            <li key={owner.address} className="flex items-center gap-2 text-sm">
              <Avatar name={owner.name} className="size-6" />
              <Address address={owner.address} label={owner.name} />
              <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                {signature ? (
                  <span className="inline-flex items-center gap-1 text-success-foreground">
                    <Check className="size-3" aria-hidden="true" />
                    {t('Signed')} {formatRelative(signature.at)}
                  </span>
                ) : (
                  t('Not signed')
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** What a Safe transaction will call, decoded. Delegatecalls are called out. */
export function DecodedCalls({ calls }: { calls: DecodedCall[] }) {
  return (
    <ol className="grid gap-3">
      {calls.map((call, index) => (
        <li key={`${call.method}-${index}`} className="rounded-lg border">
          <div className="flex flex-wrap items-center gap-2 border-b bg-surface-muted px-3 py-2">
            <span className="num text-xs text-muted-foreground">
              #{index + 1}
            </span>
            <code className="num text-sm font-medium">{call.method}()</code>
            <span className="text-sm text-muted-foreground">{t('on')}</span>
            <Address address={call.to} label={call.toLabel} />
            {call.operation === 1 && (
              <Badge tone="danger" className="ml-auto">
                <TriangleAlert aria-hidden="true" />
                {t('Delegatecall')}
              </Badge>
            )}
          </div>
          {call.operation === 1 && (
            <Alert tone="danger" className="m-3 mb-0">
              {t(
                'This call runs another contract’s code with the Safe’s own storage and funds. Sign only if you can verify exactly what it does.',
              )}
            </Alert>
          )}
          <dl className="divide-y text-sm">
            {call.params.map((param) => (
              <Row
                key={param.name}
                label={
                  <>
                    {param.name}{' '}
                    <span className="num text-xs text-subtle-foreground">
                      {param.type}
                    </span>
                  </>
                }
              >
                {param.value}
              </Row>
            ))}
            {call.params.length === 0 && (
              <Row label={t('Parameters')}>{t('none')}</Row>
            )}
            <Row label="value">{call.value}</Row>
            <Row label="operation">
              {call.operation} ({call.operation === 0 ? 'call' : 'delegatecall'}
              )
            </Row>
            <Row label="data">{call.data}</Row>
          </dl>
        </li>
      ))}
    </ol>
  );
}

function Row({ children, label }: { children: ReactNode; label: ReactNode }) {
  return (
    <div className="grid gap-x-3 px-3 py-1.5 sm:grid-cols-[10rem_1fr]">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="num break-all">{children}</dd>
    </div>
  );
}
