import { ChevronDown, PenLine, Send } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Address, TxHash } from '@/components/domain/chain';
import { DiffView, KeyValueList } from '@/components/domain/display';
import {
  DecodedCalls,
  SignatureProgress,
  TypedDataTable,
  WalletActionButton,
} from '@/components/domain/signing';
import { StatusBadge } from '@/components/domain/status';
import { ErrorState } from '@/components/feedback';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Alert, Skeleton } from '@/components/ui/misc';
import {
  fetchExecCall,
  useCancelGovernanceTx,
  useGovernanceTx,
  useReportGovernanceSubmitted,
  useSubmitGovernanceSignature,
} from '@/features/controls/api';
import { useOrgScope } from '@/features/orgs/org-scope';
import { errorMessage } from '@/lib/api/http';
import type { GovernanceTx, TypedData } from '@/lib/api/types';
import { formatDateTime } from '@/lib/format';
import { t } from '@/lib/i18n';
import { governanceStatus } from '@/lib/status';
import { useWallet } from '@/lib/wallet/wallet-context';

/**
 * Sign and execute controls for one Safe transaction (WEB-025).
 * Also embedded in the setup wizard, so it takes the loaded tx as props.
 */
export function GovernanceActions({
  tx,
  typedData,
}: {
  tx: GovernanceTx;
  typedData: TypedData;
}) {
  const scope = useOrgScope();
  const wallet = useWallet();
  const submitSignature = useSubmitGovernanceSignature(scope.orgId);
  const reportSubmitted = useReportGovernanceSubmitted(scope.orgId);
  const cancel = useCancelGovernanceTx(scope.orgId);
  const [showTypedData, setShowTypedData] = useState(false);

  const owners = tx.owners.map((owner) => owner.address);
  const alreadySigned = tx.signatures.some(
    (signature) =>
      signature.owner.toLowerCase() === wallet.address?.toLowerCase(),
  );
  const ownersOnly = {
    addresses: owners,
    message: t(
      'The connected wallet is not an owner of this Safe. Connect an owner wallet to sign.',
    ),
  };

  if (tx.status === 'Executed') {
    return (
      <Alert tone="success" title={t('Executed on-chain')}>
        {tx.txHash && <TxHash hash={tx.txHash} />}
      </Alert>
    );
  }
  if (tx.status === 'Failed') {
    return (
      <Alert tone="danger" title={t('Reverted on-chain')}>
        {tx.failureReason} {tx.txHash && <TxHash hash={tx.txHash} />}
      </Alert>
    );
  }
  if (tx.status === 'Superseded') {
    return (
      <Alert tone="neutral" title={t('Superseded')}>
        {t(
          'Another transaction with the same Safe nonce replaced this one. It can no longer be signed or executed.',
        )}
      </Alert>
    );
  }
  if (tx.status === 'Executing') {
    return (
      <Alert tone="info" title={t('Sent — waiting for the network')}>
        {tx.txHash && <TxHash hash={tx.txHash} />}
      </Alert>
    );
  }

  return (
    <div className="grid gap-4">
      <SignatureProgress tx={tx} />

      <div>
        <button
          type="button"
          aria-expanded={showTypedData}
          onClick={() => setShowTypedData((value) => !value)}
          className="flex items-center gap-1.5 text-sm font-medium text-foreground hover:underline"
        >
          <ChevronDown
            className={`size-4 transition-transform ${showTypedData ? 'rotate-180' : ''}`}
            aria-hidden="true"
          />
          {t('Review what you sign')}
        </button>
        {showTypedData && (
          <div className="mt-2 grid gap-2">
            <p className="text-sm text-muted-foreground">
              {t(
                'This is the exact SafeTx object sent to your wallet. Check that your wallet shows the same to, data, operation and nonce. If you cannot verify it, do not sign it.',
              )}
            </p>
            <TypedDataTable typedData={typedData} />
          </div>
        )}
      </div>

      {tx.status === 'AwaitingSignatures' && (
        <WalletActionButton
          variant="primary"
          size="lg"
          chainId={typedData.domain.chainId}
          requiredAddresses={ownersOnly}
          blockedReason={
            alreadySigned
              ? t('This wallet has already signed. Waiting for another owner.')
              : undefined
          }
          action={async () => {
            const signature = await wallet.signTypedData(typedData);
            await submitSignature.mutateAsync({ id: tx.id, signature });
            toast.success(t('Signature recorded'));
          }}
        >
          <PenLine aria-hidden="true" />
          {t('Sign with wallet')}
        </WalletActionButton>
      )}

      {tx.status === 'ReadyToExecute' && (
        <WalletActionButton
          variant="primary"
          size="lg"
          chainId={typedData.domain.chainId}
          requiredAddresses={ownersOnly}
          action={async () => {
            const call = await fetchExecCall(scope.orgId, tx.id);
            const txHash = await wallet.sendTransaction(call);
            await reportSubmitted.mutateAsync({ id: tx.id, txHash });
            toast.success(t('Sent — waiting for the network'));
          }}
        >
          <Send aria-hidden="true" />
          {t('Execute transaction')}
        </WalletActionButton>
      )}

      <Button
        variant="ghost"
        size="sm"
        className="justify-self-start"
        loading={cancel.isPending}
        onClick={() =>
          cancel.mutate(tx.id, {
            onError: (error) => toast.error(errorMessage(error)),
          })
        }
      >
        {t('Cancel this transaction')}
      </Button>
    </div>
  );
}

export function GovernanceDetail({ id }: { id: string }) {
  const scope = useOrgScope();
  const query = useGovernanceTx(scope.orgId, id);

  if (query.isPending) {
    return (
      <Card className="p-4" aria-busy="true">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="mt-3 h-4 w-full" />
        <Skeleton className="mt-6 h-40 w-full" />
      </Card>
    );
  }
  if (query.isError) {
    return (
      <Card>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    );
  }
  const { governanceTx: tx, typedData } = query.data;

  return (
    <div className="grid gap-4">
      <Card>
        <CardContent>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h2 className="text-xl font-semibold">{tx.title}</h2>
            <StatusBadge meta={governanceStatus(tx.status)} />
          </div>
          <p className="mt-2 text-base text-muted-foreground">{tx.summary}</p>
          <KeyValueList
            className="mt-4"
            items={[
              {
                label: t('Safe'),
                value: (
                  <Address address={tx.safeAddress} label={tx.safeLabel} />
                ),
              },
              {
                label: t('Safe nonce'),
                value: <span className="num">{tx.nonce}</span>,
              },
              {
                label: t('Proposed'),
                value: `${tx.createdBy} · ${formatDateTime(tx.createdAt)}`,
              },
            ]}
          />
        </CardContent>
      </Card>

      {tx.diff && tx.diff.length > 0 && (
        <Card>
          <CardHeader
            title={t('What changes')}
            description={t(
              'Compared with the configuration that is active on-chain now.',
            )}
          />
          <CardContent>
            <DiffView diff={tx.diff} />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader
          title={t('Decoded calls')}
          description={t('What the Safe will execute, in order.')}
        />
        <CardContent>
          <DecodedCalls calls={tx.calls} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader title={t('Signatures')} />
        <CardContent>
          <GovernanceActions tx={tx} typedData={typedData} />
        </CardContent>
      </Card>
    </div>
  );
}
