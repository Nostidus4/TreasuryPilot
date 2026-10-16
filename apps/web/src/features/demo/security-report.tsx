import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { KeyValueList } from '@/components/domain/display';
import { t } from '@/lib/i18n';

import type { ScenarioView } from './types';

/**
 * The stored security report. It keeps two things apart: the app refusing the invoice, and the
 * contract-level negative test on a separate fixture.
 */
export function SecurityReportDialog({
  data,
  onOpenChange,
  open,
}: {
  data: ScenarioView;
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const x = data.fixture.securityScenario;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {t('Security evidence')}
            <Badge tone="warning" data-testid="security-report-badge">
              {t('Simulated')}
            </Badge>
          </DialogTitle>
          <DialogDescription>
            {x.contractTestReference} ·{' '}
            {t('stored report, not a live test run')}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4" data-testid="security-report">
          <section>
            <h3 className="mb-2 text-base font-semibold">
              {t('1. App block (this product)')}
            </h3>
            <KeyValueList
              items={[
                { label: t('Invoice'), value: `${x.number} · 250 USDC` },
                {
                  label: t('Recipient'),
                  value: `${x.recipientAlias} (not in the payee registry)`,
                },
                {
                  label: t('Policy'),
                  value: `${t('Unknown payee')}: ${data.fixture.mandate.unknownRecipientPolicy}`,
                },
                { label: t('Result'), value: x.expectedOnSubmit },
                {
                  label: t('Created'),
                  value: t('No approval, reserve, plan, payment or broadcast'),
                },
              ]}
            />
          </section>
          <section>
            <h3 className="mb-2 text-base font-semibold">
              {t('2. Contract-negative test (separate clean fixture)')}
            </h3>
            <KeyValueList
              items={[
                { label: t('Reference'), value: x.contractTestReference },
                {
                  label: t('Setup'),
                  value: t(
                    'Unspent request with valid authority; only the recipient is mutated',
                  ),
                },
                {
                  label: t('Expected'),
                  value: t('The contract rejects the mutated payload'),
                },
                {
                  label: t('Isolation'),
                  value: t('Does not reuse the already-paid invoice A'),
                },
              ]}
            />
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
