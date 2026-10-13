import { Command } from 'cmdk';
import { FileText, Plus, Search, Upload } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { useOrgScope } from '@/features/orgs/org-scope';
import { useRequests } from '@/features/requests/api';
import { t } from '@/lib/i18n';
import { requestStatus } from '@/lib/status';

const itemClass =
  'flex cursor-default items-center gap-2.5 rounded-md px-2.5 py-2 text-base data-[selected=true]:bg-muted [&_svg]:size-4 [&_svg]:text-muted-foreground';
const headingClass =
  '[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-subtle-foreground';

/** ⌘K: jump to a screen, start an action, or find a request. */
export function CommandMenu({
  onOpenChange,
  open,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const scope = useOrgScope();
  const navigate = useNavigate();
  const requests = useRequests(scope.orgId);
  const go = (to: string) => {
    onOpenChange(false);
    navigate(to);
  };
  const { base, tBase } = scope;

  const pages: Array<[string, string]> = [
    [t('Overview'), tBase],
    [t('Approvals'), `${base}/approvals`],
    [t('Governance'), `${base}/governance`],
    [t('Review'), `${base}/review`],
    [t('Requests'), `${base}/requests`],
    [t('Plans'), `${tBase}/plans`],
    [t('Reconciliation'), `${base}/reconciliation`],
    [t('Mandate'), `${tBase}/mandate`],
    [t('Payees'), `${tBase}/payees`],
    [t('Fees'), `${tBase}/settings/fees`],
    [t('Metrics'), `${base}/metrics`],
    [t('Members'), `${base}/members`],
    [t('Wallets'), '/me/wallets'],
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="top-[20%] translate-y-0 gap-0 overflow-hidden p-0"
        aria-describedby={undefined}
      >
        <DialogTitle className="sr-only">{t('Command menu')}</DialogTitle>
        <Command label={t('Command menu')} loop>
          <div className="flex items-center gap-2 border-b px-3">
            <Search
              className="size-4 text-subtle-foreground"
              aria-hidden="true"
            />
            <Command.Input
              autoFocus
              placeholder={t('Search requests, screens and actions…')}
              className="h-11 flex-1 bg-transparent text-base placeholder:text-subtle-foreground focus-visible:ring-0 focus-visible:ring-offset-0"
            />
          </div>
          <Command.List className="max-h-80 overflow-y-auto p-1.5">
            <Command.Empty className="px-3 py-8 text-center text-base text-muted-foreground">
              {t('Nothing matches. Try a vendor name or an invoice number.')}
            </Command.Empty>
            <Command.Group heading={t('Actions')} className={headingClass}>
              <Command.Item
                className={itemClass}
                onSelect={() => go(`${base}/requests/upload`)}
              >
                <Upload aria-hidden="true" />
                {t('Upload an invoice')}
              </Command.Item>
              <Command.Item
                className={itemClass}
                onSelect={() => go(`${base}/requests/new`)}
              >
                <Plus aria-hidden="true" />
                {t('New payment request')}
              </Command.Item>
            </Command.Group>
            <Command.Group heading={t('Go to')} className={headingClass}>
              {pages.map(([label, to]) => (
                <Command.Item
                  key={to}
                  className={itemClass}
                  onSelect={() => go(to)}
                >
                  {label}
                </Command.Item>
              ))}
            </Command.Group>
            {requests.data && requests.data.items.length > 0 && (
              <Command.Group heading={t('Requests')} className={headingClass}>
                {requests.data.items.map((request) => (
                  <Command.Item
                    key={request.id}
                    className={itemClass}
                    value={`${request.invoiceNumber} ${request.vendorName}`}
                    onSelect={() => go(`${base}/requests/${request.id}`)}
                  >
                    <FileText aria-hidden="true" />
                    <span className="num">{request.invoiceNumber}</span>
                    <span className="truncate text-muted-foreground">
                      {request.vendorName}
                    </span>
                    <span className="ml-auto text-xs text-subtle-foreground">
                      {requestStatus(request.status).label}
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
