import { Link2, Trash2, Wallet as WalletIcon } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Address } from '@/components/domain/chain';
import { ConnectWalletDialog } from '@/components/domain/signing';
import { EmptyState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Alert } from '@/components/ui/misc';
import { useLinkWallet, useMe, useUnlinkWallet } from '@/features/auth/api';
import { AccountLayout } from '@/features/orgs/orgs-pages';
import { errorMessage } from '@/lib/api/http';
import { formatDate } from '@/lib/format';
import { t } from '@/lib/i18n';
import { isUserRejection, useWallet } from '@/lib/wallet/wallet-context';

/**
 * Wallet linking with SIWE (WEB-003). Linking proves control of an address;
 * it does not grant any on-chain permission by itself.
 */
export function WalletsPage() {
  const me = useMe();
  const wallet = useWallet();
  const link = useLinkWallet();
  const unlink = useUnlinkWallet();
  const [connectOpen, setConnectOpen] = useState(false);

  const linked = me.data?.wallets ?? [];
  const connectedIsLinked = linked.some(
    (item) => item.address.toLowerCase() === wallet.address?.toLowerCase(),
  );

  const linkConnected = () => {
    if (!wallet.address) return;
    link.mutate(
      {
        address: wallet.address,
        signMessage: wallet.signMessage,
      },
      {
        onSuccess: () => toast.success(t('Wallet linked')),
        onError: (error) => {
          if (isUserRejection(error)) {
            link.reset();
            toast.info(t('Rejected in your wallet'), {
              description: t('Nothing was signed. The wallet is not linked.'),
            });
          }
        },
      },
    );
  };

  return (
    <AccountLayout>
      <Page
        width="narrow"
        title={t('Wallets')}
        description={t(
          'Link the wallets you sign with. Approvals and governance signatures are accepted only from a wallet linked to your account.',
        )}
      >
        <div className="grid gap-6">
          <Card>
            <CardHeader
              title={t('Connected wallet')}
              description={t('The wallet this browser will sign with.')}
            />
            <CardContent className="grid gap-3">
              {wallet.address ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Address address={wallet.address} />
                    {wallet.kind === 'demo' && (
                      <Badge tone="warning">{t('Demo signer')}</Badge>
                    )}
                    {connectedIsLinked ? (
                      <Badge tone="success">
                        {t('Linked to your account')}
                      </Badge>
                    ) : (
                      <Badge tone="warning">{t('Not linked')}</Badge>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto"
                      onClick={() => wallet.disconnect()}
                    >
                      {t('Disconnect')}
                    </Button>
                  </div>
                  {!connectedIsLinked && (
                    <div>
                      <p className="text-sm text-muted-foreground">
                        {t(
                          'Sign a short message to prove you control this address. It costs no gas and moves no funds.',
                        )}
                      </p>
                      <Button
                        variant="primary"
                        className="mt-3"
                        loading={link.isPending}
                        onClick={linkConnected}
                      >
                        <Link2 aria-hidden="true" />
                        {t('Sign to link this wallet')}
                      </Button>
                    </div>
                  )}
                  {link.isError && (
                    <Alert tone="danger" title={t('The wallet was not linked')}>
                      {errorMessage(link.error)}
                    </Alert>
                  )}
                </>
              ) : (
                <div>
                  <p className="text-base text-muted-foreground">
                    {t('No wallet is connected in this browser.')}
                  </p>
                  <Button
                    variant="primary"
                    className="mt-3"
                    onClick={() => setConnectOpen(true)}
                  >
                    <WalletIcon aria-hidden="true" />
                    {t('Connect wallet')}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader title={t('Linked wallets')} />
            <QueryBoundary query={me}>
              {() =>
                linked.length === 0 ? (
                  <EmptyState
                    icon={WalletIcon}
                    title={t('No linked wallets')}
                    description={t(
                      'Connect a wallet above and sign the linking message. You need one to approve requests or sign governance transactions.',
                    )}
                  />
                ) : (
                  <ul className="divide-y">
                    {linked.map((item) => (
                      <li
                        key={item.address}
                        className="flex flex-wrap items-center gap-3 px-4 py-3"
                      >
                        <Address address={item.address} />
                        <span className="text-sm text-muted-foreground">
                          {t('Linked {{date}}', {
                            date: formatDate(item.linkedAt),
                          })}
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="ml-auto"
                          loading={
                            unlink.isPending &&
                            unlink.variables === item.address
                          }
                          onClick={() =>
                            unlink.mutate(item.address, {
                              onSuccess: () =>
                                toast.success(t('Wallet unlinked')),
                              onError: (error) =>
                                toast.error(errorMessage(error)),
                            })
                          }
                        >
                          <Trash2 aria-hidden="true" />
                          {t('Unlink')}
                        </Button>
                      </li>
                    ))}
                  </ul>
                )
              }
            </QueryBoundary>
          </Card>
        </div>
        <ConnectWalletDialog open={connectOpen} onOpenChange={setConnectOpen} />
      </Page>
    </AccountLayout>
  );
}
