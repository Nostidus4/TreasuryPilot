import { PenLine } from 'lucide-react';
import { useParams } from 'react-router-dom';

import { StatusBadge } from '@/components/domain/status';
import { EmptyState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import {
  InboxGroup,
  InboxItem,
  SplitInbox,
} from '@/components/layout/split-inbox';
import { Card } from '@/components/ui/card';
import { useGovernanceTxs } from '@/features/governance/api';
import { GovernanceDetail } from '@/features/governance/governance-detail';
import { useOrgScope } from '@/features/orgs/org-scope';
import type { GovernanceTxView } from '@/lib/api/types';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { governanceStatus } from '@/lib/status';

function Row({
  selected,
  to,
  tx,
}: {
  selected: boolean;
  to: string;
  tx: GovernanceTxView;
}) {
  return (
    <InboxItem to={to} selected={selected}>
      <p className="truncate text-base font-medium">{tx.title}</p>
      <p className="mt-0.5 flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          {t('{{signed}}/{{threshold}} signed', {
            signed: tx.signatures.length,
            threshold: tx.threshold,
          })}{' '}
          · {formatRelative(tx.createdAt)}
        </span>
        <StatusBadge meta={governanceStatus(tx.status)} />
      </p>
    </InboxItem>
  );
}

/** Governance signing inbox (WEB-025): sign and execute Safe transactions in-app. */
export function GovernancePage() {
  const scope = useOrgScope();
  const { g: selectedId } = useParams();
  const query = useGovernanceTxs(scope.orgId);
  const listPath = `${scope.base}/governance`;

  return (
    <Page
      title={t('Governance')}
      description={t(
        'Changes to the mandate, payees and exceptions are Safe transactions. Owners sign them here; nothing changes until the threshold is met and the transaction executes.',
      )}
      width="wide"
    >
      <QueryBoundary query={query}>
        {({ items }) => {
          if (items.length === 0) {
            return (
              <Card>
                <EmptyState
                  icon={PenLine}
                  title={t('No governance transactions')}
                  description={t(
                    'When someone changes the mandate, registers a payee or grants an exception, the transaction to sign appears here.',
                  )}
                />
              </Card>
            );
          }
          const groups: Array<[string, GovernanceTxView[]]> = [
            [
              t('Needs signatures'),
              items.filter((tx) => tx.status === 'AwaitingSignatures'),
            ],
            [
              t('Ready to execute'),
              items.filter(
                (tx) =>
                  tx.status === 'ReadyToExecute' || tx.status === 'Executing',
              ),
            ],
            [
              t('History'),
              items.filter((tx) =>
                ['Executed', 'Failed', 'Superseded', 'Cancelled'].includes(
                  tx.status,
                ),
              ),
            ],
          ];
          return (
            <SplitInbox
              backTo={listPath}
              hasSelection={Boolean(selectedId)}
              listLabel={t('Governance transactions')}
              list={groups
                .filter(([, group]) => group.length > 0)
                .map(([label, group]) => (
                  <InboxGroup key={label} label={label} count={group.length}>
                    {group.map((tx) => (
                      <Row
                        key={tx.id}
                        tx={tx}
                        to={`${listPath}/${tx.id}`}
                        selected={tx.id === selectedId}
                      />
                    ))}
                  </InboxGroup>
                ))}
              detail={
                selectedId ? (
                  <GovernanceDetail key={selectedId} id={selectedId} />
                ) : (
                  <Card>
                    <EmptyState
                      icon={PenLine}
                      title={t('Select a transaction')}
                      description={t(
                        'Choose a transaction to see its decoded calls, what it changes and who has signed.',
                      )}
                    />
                  </Card>
                )
              }
            />
          );
        }}
      </QueryBoundary>
    </Page>
  );
}
