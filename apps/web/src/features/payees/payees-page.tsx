import type { ColumnDef } from '@tanstack/react-table';
import { MoreHorizontal, Plus, ShieldCheck } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { DataTable } from '@/components/data-table';
import { Address, CountdownChip } from '@/components/domain/chain';
import { StatusBadge } from '@/components/domain/status';
import { EmptyState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Select } from '@/components/ui/controls';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Field, Input, Textarea } from '@/components/ui/input';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/menus';
import { Alert } from '@/components/ui/misc';
import {
  useCreateVendor,
  usePayees,
  usePayeeTx,
  useProposePayee,
  useReplacePayeeAddress,
  useVerifyPayeeOob,
} from '@/features/controls/api';
import { useTreasuryScope } from '@/features/orgs/org-scope';
import { useVendors } from '@/features/requests/api';
import { errorMessage, isApiError } from '@/lib/api/http';
import type { components } from '@/lib/api/schema';
import type { Payee } from '@/lib/api/types';
import { formatDate } from '@/lib/format';
import { t } from '@/lib/i18n';
import { payeeStatus } from '@/lib/status';

type OobMethod = components['schemas']['OobMethod'];

const NEW_VENDOR = '__new__';

function ProposeDialog({
  onOpenChange,
  open,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const scope = useTreasuryScope();
  const vendors = useVendors(scope.orgId);
  const propose = useProposePayee(scope.orgId, scope.treasuryId);
  const createVendor = useCreateVendor(scope.orgId);
  const [vendorId, setVendorId] = useState<string>();
  const [vendorName, setVendorName] = useState('');
  const [label, setLabel] = useState('');
  const [address, setAddress] = useState('');
  const failure = propose.error ?? createVendor.error;
  const fieldErrors = isApiError(failure)
    ? Object.fromEntries(
        (failure.problem.errors ?? []).map((item) => [
          item.field,
          item.message,
        ]),
      )
    : {};
  const reset = () => {
    setVendorId(undefined);
    setVendorName('');
    setLabel('');
    setAddress('');
    propose.reset();
    createVendor.reset();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) reset();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('Propose a payee')}</DialogTitle>
          <DialogDescription>
            {t(
              'The address is screened first. It can be paid only after an owner confirms it with the vendor, the Safe owners register it, and the cooling period ends.',
            )}
          </DialogDescription>
        </DialogHeader>
        <form
          id="propose-payee"
          className="grid gap-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void (async () => {
              try {
                const id =
                  vendorId === NEW_VENDOR
                    ? (await createVendor.mutateAsync(vendorName.trim())).vendor
                        .id
                    : vendorId;
                if (!id) return;
                await propose.mutateAsync({
                  vendorId: id,
                  label: label.trim() || t('Receiving wallet'),
                  address: address.trim(),
                });
                toast.success(t('Payee proposed — screening started'));
                onOpenChange(false);
                reset();
              } catch (error) {
                if (screeningBlocked(error)) {
                  onOpenChange(false);
                  reset();
                }
              }
            })();
          }}
        >
          <Field
            htmlFor="payee-vendor"
            label={t('Vendor')}
            error={fieldErrors.vendorId}
          >
            <Select
              id="payee-vendor"
              value={vendorId}
              onValueChange={setVendorId}
              placeholder={t('Choose a vendor')}
              invalid={Boolean(fieldErrors.vendorId)}
              options={[
                ...(vendors.data?.items ?? []).map((vendor) => ({
                  value: vendor.id,
                  label: vendor.name,
                })),
                { value: NEW_VENDOR, label: t('New vendor…') },
              ]}
            />
          </Field>
          {vendorId === NEW_VENDOR && (
            <Field htmlFor="payee-vendor-name" label={t('Vendor name')}>
              <Input
                id="payee-vendor-name"
                value={vendorName}
                onChange={(event) => setVendorName(event.target.value)}
              />
            </Field>
          )}
          <Field htmlFor="payee-label" label={t('Label')} optional>
            <Input
              id="payee-label"
              value={label}
              placeholder={t('e.g. Main receiving wallet')}
              onChange={(event) => setLabel(event.target.value)}
            />
          </Field>
          <Field
            htmlFor="payee-address"
            label={t('Wallet address')}
            error={fieldErrors.address}
            hint={t(
              'Copy it from a channel you trust, not from the invoice alone.',
            )}
          >
            <Input
              id="payee-address"
              className="num"
              placeholder="0x…"
              value={address}
              aria-invalid={Boolean(fieldErrors.address)}
              onChange={(event) => setAddress(event.target.value)}
            />
          </Field>
          {failure && Object.keys(fieldErrors).length === 0 && (
            <Alert tone="danger">{errorMessage(failure)}</Alert>
          )}
        </form>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}>{t('Cancel')}</Button>
          <Button
            type="submit"
            form="propose-payee"
            variant="primary"
            loading={propose.isPending || createVendor.isPending}
          >
            {t('Propose payee')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const oobMethods = [
  { value: 'PHONE', label: 'Phone call to a known number' },
  { value: 'IN_PERSON', label: 'In person' },
  { value: 'SIGNED_LETTER', label: 'Signed letter' },
  { value: 'OTHER', label: 'Other' },
];

function VerifyDialog({
  onClose,
  payee,
  vendorName,
}: {
  onClose: () => void;
  payee: Payee | null;
  vendorName: string;
}) {
  const scope = useTreasuryScope();
  const verify = useVerifyPayeeOob(scope.orgId, scope.treasuryId);
  const [method, setMethod] = useState<OobMethod>('PHONE');
  const [note, setNote] = useState('');
  return (
    <Dialog open={payee !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('Record the out-of-band check')}</DialogTitle>
          <DialogDescription>
            {t(
              'Confirm this address with {{vendor}} through a channel that does not depend on the invoice or email that supplied it.',
              { vendor: vendorName },
            )}
          </DialogDescription>
        </DialogHeader>
        {payee && (
          <div className="rounded-lg border bg-surface-muted p-3">
            <Address address={payee.address} full />
          </div>
        )}
        <form
          id="verify-oob"
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!payee) return;
            verify.mutate(
              { id: payee.id, method, note },
              {
                onSuccess: () => {
                  toast.success(t('Check recorded'));
                  setNote('');
                  onClose();
                },
              },
            );
          }}
        >
          <Field htmlFor="oob-method" label={t('How did you confirm it?')}>
            <Select
              id="oob-method"
              value={method}
              onValueChange={(value) => setMethod(value as OobMethod)}
              options={oobMethods.map((item) => ({
                ...item,
                label: t(item.label),
              }))}
            />
          </Field>
          <Field
            htmlFor="oob-note"
            label={t('Who confirmed it, and when?')}
            error={verify.isError ? errorMessage(verify.error) : undefined}
          >
            <Textarea
              id="oob-note"
              required
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </Field>
        </form>
        <DialogFooter>
          <Button onClick={onClose}>{t('Cancel')}</Button>
          <Button
            type="submit"
            form="verify-oob"
            variant="primary"
            loading={verify.isPending}
            disabled={!note.trim()}
          >
            {t('Record check')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The API stores a blocked payee as ScreeningFailed, then answers 422/503. */
function screeningBlocked(error: unknown) {
  const hit = isApiError(error, 'SCREENING_HIT');
  if (!hit && !isApiError(error, 'DATA_MISSING')) return false;
  toast.error(
    hit
      ? t('The address matched a sanctions list, so the payee is blocked.')
      : t('Screening could not complete, so the payee is blocked.'),
    { description: t('See the “Screening failed” row in the list.') },
  );
  return true;
}

type Change = { kind: 'deactivate' | 'replace'; payee: Payee };

/** Owner-only: deactivation, or an address change that restarts cooling. */
function ChangeDialog({
  change,
  onClose,
  vendorName,
}: {
  change: Change | null;
  onClose: () => void;
  vendorName: string;
}) {
  const scope = useTreasuryScope();
  const navigate = useNavigate();
  const deactivate = usePayeeTx(scope.orgId, scope.treasuryId);
  const replacement = useReplacePayeeAddress(scope.orgId, scope.treasuryId);
  const [reason, setReason] = useState('');
  const [address, setAddress] = useState('');
  const replacing = change?.kind === 'replace';
  const mutation = replacing ? replacement : deactivate;
  const done = (txId: string) => {
    toast.success(t('Governance transaction created'));
    setReason('');
    setAddress('');
    onClose();
    navigate(`${scope.base}/governance/${txId}`);
  };
  const submit = () => {
    if (!change) return;
    if (replacing)
      replacement.mutate(
        { id: change.payee.id, address: address.trim(), reason },
        {
          onSuccess: (r) => done(r.deactivationGovernanceTx.id),
          onError: (error) => {
            if (screeningBlocked(error)) {
              setAddress('');
              onClose();
            }
          },
        },
      );
    else
      deactivate.mutate(
        { id: change.payee.id, kind: 'deactivation', reason },
        { onSuccess: (r) => done(r.governanceTx.id) },
      );
  };
  return (
    <Dialog
      open={change !== null}
      onOpenChange={(open) => {
        if (!open) {
          mutation.reset();
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {replacing ? t('Change payee address') : t('Deactivate payee')}
          </DialogTitle>
          <DialogDescription>
            {replacing
              ? t(
                  '{{vendor}} will stop being payable at the current address once the Safe owners sign the deactivation. The new address is screened, confirmed with the vendor and registered like a new payee, then waits out the full cooling period before it can be paid. Payments to {{vendor}} are on hold until then.',
                  { vendor: vendorName },
                )
              : t(
                  'Requests to {{vendor}} can no longer be paid once the Safe owners sign.',
                  { vendor: vendorName },
                )}
          </DialogDescription>
        </DialogHeader>
        <form
          id="change-payee"
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          {replacing && (
            <Field htmlFor="replace-address" label={t('New wallet address')}>
              <Input
                id="replace-address"
                className="num"
                placeholder="0x…"
                value={address}
                onChange={(event) => setAddress(event.target.value)}
              />
            </Field>
          )}
          <Field
            htmlFor="change-reason"
            label={t('Reason')}
            error={mutation.isError ? errorMessage(mutation.error) : undefined}
          >
            <Textarea
              id="change-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </Field>
        </form>
        <DialogFooter>
          <Button onClick={onClose}>{t('Cancel')}</Button>
          <Button
            type="submit"
            form="change-payee"
            variant={replacing ? 'primary' : 'danger'}
            loading={mutation.isPending}
            disabled={!reason.trim() || (replacing && !address.trim())}
          >
            {replacing
              ? t('Create deactivation transaction')
              : t('Deactivate payee')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Payee registry (WEB-006): propose → screen → verify → register → cool down. */
export function PayeesPage() {
  const scope = useTreasuryScope();
  const navigate = useNavigate();
  const query = usePayees(scope.orgId, scope.treasuryId);
  const vendors = useVendors(scope.orgId);
  const vendorNames = useMemo(
    () => new Map((vendors.data?.items ?? []).map((v) => [v.id, v.name])),
    [vendors.data],
  );
  const nameOf = useCallback(
    (payee: Payee) => vendorNames.get(payee.vendorId) ?? t('Vendor'),
    [vendorNames],
  );
  const payeeTx = usePayeeTx(scope.orgId, scope.treasuryId);
  const [change, setChange] = useState<Change | null>(null);
  const [proposeOpen, setProposeOpen] = useState(false);
  const [verifying, setVerifying] = useState<Payee | null>(null);
  const isOwner = scope.can('OWN');
  const { base } = scope;
  const { mutate: createTx } = payeeTx;

  const columns = useMemo<Array<ColumnDef<Payee, unknown>>>(() => {
    const openTx = (payee: Payee, kind: 'registration') =>
      createTx(
        { id: payee.id, kind },
        {
          onSuccess: ({ governanceTx }) =>
            navigate(`${base}/governance/${governanceTx.id}`),
          onError: (error) => toast.error(errorMessage(error)),
        },
      );
    return [
      {
        id: 'vendor',
        header: t('Vendor'),
        accessorFn: (row) => `${nameOf(row)} ${row.label} ${row.address}`,
        cell: ({ row }) => (
          <div className="min-w-0">
            <p className="font-medium">{nameOf(row.original)}</p>
            <p className="truncate text-xs text-muted-foreground">
              {row.original.label}
            </p>
            {/* The address column is hidden at 390px; keep it visible here. */}
            <div className="mt-1 md:hidden">
              <Address address={row.original.address} />
            </div>
          </div>
        ),
      },
      {
        id: 'address',
        header: t('Address'),
        enableSorting: false,
        meta: { hideOnMobile: true },
        cell: ({ row }) => <Address address={row.original.address} />,
      },
      {
        id: 'screening',
        header: t('Screening'),
        accessorFn: (row) => row.screening?.result ?? 'PENDING',
        meta: { hideOnMobile: true },
        cell: ({ row }) => {
          const { result, checkedAt } = row.original.screening ?? {};
          return (
            <div>
              <Badge
                tone={
                  result === 'CLEAR' ? 'success' : result ? 'danger' : 'neutral'
                }
              >
                {result === 'CLEAR'
                  ? t('Clear')
                  : result === 'HIT'
                    ? t('Hit')
                    : result === 'ERROR'
                      ? t('Could not complete')
                      : t('Running')}
              </Badge>
              {checkedAt && (
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {formatDate(checkedAt)}
                </p>
              )}
            </div>
          );
        },
      },
      {
        id: 'status',
        header: t('Status'),
        accessorKey: 'status',
        cell: ({ row }) => (
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusBadge
              meta={payeeStatus(
                row.original.status,
                Boolean(row.original.oobVerifiedAt),
              )}
            />
            {row.original.status === 'Cooling' && row.original.activeFrom && (
              <CountdownChip
                label={t('Payable in')}
                until={row.original.activeFrom}
              />
            )}
          </div>
        ),
      },
      {
        id: 'actions',
        header: () => <span className="sr-only">{t('Actions')}</span>,
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => {
          const payee = row.original;
          if (!isOwner) return null;
          if (payee.status === 'AwaitingOwner' && !payee.oobVerifiedAt) {
            return (
              <Button size="sm" onClick={() => setVerifying(payee)}>
                {t('Record check')}
              </Button>
            );
          }
          if (payee.status === 'AwaitingOwner') {
            if (payee.registrationTxId)
              return (
                <Button
                  size="sm"
                  onClick={() =>
                    navigate(`${base}/governance/${payee.registrationTxId}`)
                  }
                >
                  {t('View transaction')}
                </Button>
              );
            return (
              <Button
                size="sm"
                variant="primary"
                onClick={() => openTx(payee, 'registration')}
              >
                {t('Register on-chain')}
              </Button>
            );
          }
          if (payee.status === 'Active' || payee.status === 'Cooling') {
            return (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t('Actions for {{vendor}}', {
                      vendor: nameOf(payee),
                    })}
                  >
                    <MoreHorizontal aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={() => setChange({ kind: 'replace', payee })}
                  >
                    {t('Change address (restarts cooling)')}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    destructive
                    onSelect={() => setChange({ kind: 'deactivate', payee })}
                  >
                    {t('Deactivate (governance transaction)')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            );
          }
          return null;
        },
      },
    ];
  }, [base, createTx, isOwner, nameOf, navigate]);

  return (
    <Page
      width="wide"
      title={t('Payees')}
      description={t(
        'The contract pays only registered addresses. A new address waits out a cooling period, so a changed address on an invoice cannot be paid quickly.',
      )}
      actions={
        scope.can('OPR', 'ADM', 'OWN') && (
          <Button variant="primary" onClick={() => setProposeOpen(true)}>
            <Plus aria-hidden="true" />
            {t('Propose payee')}
          </Button>
        )
      }
    >
      <Card className="overflow-hidden">
        <QueryBoundary query={query}>
          {({ items }) => (
            <DataTable
              columns={columns}
              data={items}
              getRowId={(row) => row.id}
              searchPlaceholder={t('Search vendor or address')}
              empty={
                <EmptyState
                  icon={ShieldCheck}
                  title={t('No payees yet')}
                  description={t(
                    'Propose the first payee. After screening, an owner confirms the address with the vendor and the Safe owners register it.',
                  )}
                  action={
                    <Button
                      variant="primary"
                      onClick={() => setProposeOpen(true)}
                    >
                      <Plus aria-hidden="true" />
                      {t('Propose payee')}
                    </Button>
                  }
                />
              }
            />
          )}
        </QueryBoundary>
      </Card>
      <ProposeDialog open={proposeOpen} onOpenChange={setProposeOpen} />
      <VerifyDialog
        payee={verifying}
        vendorName={verifying ? nameOf(verifying) : ''}
        onClose={() => setVerifying(null)}
      />
      <ChangeDialog
        change={change}
        vendorName={change ? nameOf(change.payee) : ''}
        onClose={() => setChange(null)}
      />
    </Page>
  );
}
