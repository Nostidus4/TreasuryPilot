import type { ColumnDef } from '@tanstack/react-table';
import { MoreHorizontal, UserPlus, Users } from 'lucide-react';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { DataTable } from '@/components/data-table';
import { Address } from '@/components/domain/chain';
import { EmptyState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Checkbox, Switch } from '@/components/ui/controls';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Field, Input, Label } from '@/components/ui/input';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/menus';
import { Alert, Avatar } from '@/components/ui/misc';
import { useMe } from '@/features/auth/api';
import {
  useInviteMember,
  useMembers,
  useRemoveMember,
  useUpdateMemberRoles,
  useUpdateOrgSettings,
} from '@/features/orgs/api';
import { useOrgScope } from '@/features/orgs/org-scope';
import { errorMessage } from '@/lib/api/http';
import type { Member, Role } from '@/lib/api/types';
import { t } from '@/lib/i18n';
import { roleLabels } from '@/lib/status';

const roleHelp: Record<Role, string> = {
  OWN: 'Safe owner. Signs governance: mandate, payees, exceptions, resume.',
  APR: 'Signs payment approvals with their wallet.',
  OPR: 'Creates requests, uploads invoices, runs plans.',
  FIN: 'Reconciles payments and exports.',
  GRD: 'Can pause the treasury. Cannot resume or move funds.',
  ADM: 'Manages members and organization settings.',
  AUD: 'Read-only access to everything, including the audit log.',
};
const roleOrder: Role[] = ['OWN', 'APR', 'OPR', 'FIN', 'GRD', 'ADM', 'AUD'];

function RolePicker({
  onChange,
  value,
}: {
  onChange: (roles: Role[]) => void;
  value: Role[];
}) {
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-1 text-sm font-medium">{t('Roles')}</legend>
      {roleOrder.map((role) => {
        const id = `role-${role}`;
        return (
          <div key={role} className="flex items-start gap-2.5">
            <Checkbox
              id={id}
              className="mt-0.5"
              checked={value.includes(role)}
              onCheckedChange={(checked) =>
                onChange(
                  checked === true
                    ? [...value, role]
                    : value.filter((item) => item !== role),
                )
              }
            />
            <div>
              <Label htmlFor={id}>{t(roleLabels[role])}</Label>
              <p className="text-sm text-muted-foreground">
                {t(roleHelp[role])}
              </p>
            </div>
          </div>
        );
      })}
    </fieldset>
  );
}

function MemberDialog({
  member,
  mode,
  onClose,
}: {
  member: Member | null;
  mode: 'invite' | 'edit' | null;
  onClose: () => void;
}) {
  const scope = useOrgScope();
  const invite = useInviteMember(scope.orgId);
  const update = useUpdateMemberRoles(scope.orgId);
  const [email, setEmail] = useState('');
  const [roles, setRoles] = useState<Role[]>(member?.roles ?? ['OPR']);
  const mutation = mode === 'invite' ? invite : update;

  return (
    <Dialog open={mode !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {mode === 'invite'
              ? t('Invite a member')
              : t('Roles for {{name}}', { name: member?.name ?? '' })}
          </DialogTitle>
          <DialogDescription>
            {t(
              'Roles decide what a person can do in the app. Signing still requires their own linked wallet to hold the matching on-chain permission.',
            )}
          </DialogDescription>
        </DialogHeader>
        <form
          id="member-form"
          className="grid gap-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            const done = {
              onSuccess: () => {
                toast.success(
                  mode === 'invite' ? t('Invitation sent') : t('Roles updated'),
                );
                onClose();
              },
            };
            if (mode === 'invite') invite.mutate({ email, roles }, done);
            else if (member)
              update.mutate({ userId: member.userId, roles }, done);
          }}
        >
          {mode === 'invite' && (
            <Field htmlFor="invite-email" label={t('Email')}>
              <Input
                id="invite-email"
                type="email"
                autoComplete="off"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </Field>
          )}
          <RolePicker value={roles} onChange={setRoles} />
          {mutation.isError && (
            <Alert tone="danger">{errorMessage(mutation.error)}</Alert>
          )}
        </form>
        <DialogFooter>
          <Button onClick={onClose}>{t('Cancel')}</Button>
          <Button
            type="submit"
            form="member-form"
            variant="primary"
            loading={mutation.isPending}
            disabled={roles.length === 0}
          >
            {mode === 'invite' ? t('Send invitation') : t('Save roles')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Members and roles (WEB-017). */
export function MembersPage() {
  const scope = useOrgScope();
  const me = useMe();
  const query = useMembers(scope.orgId);
  const remove = useRemoveMember(scope.orgId);
  const settings = useUpdateOrgSettings(scope.orgId);
  const [dialog, setDialog] = useState<{
    mode: 'invite' | 'edit';
    member: Member | null;
  } | null>(null);
  const isAdmin = scope.can('ADM');
  const myId = me.data?.user.id;
  const { mutate: removeMember } = remove;

  const columns = useMemo<Array<ColumnDef<Member, unknown>>>(
    () => [
      {
        id: 'member',
        header: t('Member'),
        accessorFn: (row) => `${row.name} ${row.email}`,
        cell: ({ row }) => (
          <div className="flex items-center gap-2.5">
            <Avatar name={row.original.name} />
            <div className="min-w-0">
              <p className="font-medium">
                {row.original.name}
                {row.original.userId === myId && (
                  <span className="ml-1.5 font-normal text-muted-foreground">
                    ({t('you')})
                  </span>
                )}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {row.original.email}
              </p>
              {/* Roles column is hidden at 390px; list them under the name. */}
              <p className="mt-0.5 text-xs text-muted-foreground md:hidden">
                {row.original.roles
                  .map((role) => t(roleLabels[role]))
                  .join(' · ')}
              </p>
            </div>
          </div>
        ),
      },
      {
        id: 'roles',
        header: t('Roles'),
        enableSorting: false,
        meta: { hideOnMobile: true },
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.roles.map((role) => (
              <Badge key={role}>{t(roleLabels[role])}</Badge>
            ))}
          </div>
        ),
      },
      {
        id: 'wallet',
        header: t('Linked wallet'),
        enableSorting: false,
        meta: { hideOnMobile: true },
        cell: ({ row }) =>
          row.original.wallet ? (
            <Address address={row.original.wallet} />
          ) : (
            <span className="text-muted-foreground">{t('None')}</span>
          ),
      },
      {
        id: 'status',
        header: t('Status'),
        accessorKey: 'status',
        cell: ({ row }) =>
          row.original.status === 'Active' ? (
            <Badge tone="success">{t('Active')}</Badge>
          ) : (
            <Badge tone="warning">{t('Invited')}</Badge>
          ),
      },
      {
        id: 'actions',
        header: () => <span className="sr-only">{t('Actions')}</span>,
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) =>
          isAdmin && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t('Actions for {{name}}', {
                    name: row.original.name,
                  })}
                >
                  <MoreHorizontal aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onSelect={() =>
                    setDialog({ mode: 'edit', member: row.original })
                  }
                >
                  {t('Change roles')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  destructive
                  onSelect={() =>
                    removeMember(row.original.userId, {
                      onSuccess: () => toast.success(t('Member removed')),
                      onError: (error) => toast.error(errorMessage(error)),
                    })
                  }
                >
                  {row.original.status === 'Invited'
                    ? t('Revoke invitation')
                    : t('Remove from organization')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ),
      },
    ],
    [isAdmin, myId, removeMember],
  );

  return (
    <Page
      title={t('Members')}
      description={t('Who can do what in {{org}}.', { org: scope.org.name })}
      actions={
        isAdmin && (
          <Button
            variant="primary"
            onClick={() => setDialog({ mode: 'invite', member: null })}
          >
            <UserPlus aria-hidden="true" />
            {t('Invite member')}
          </Button>
        )
      }
    >
      <div className="grid gap-4">
        <Card className="overflow-hidden">
          <QueryBoundary query={query}>
            {({ items }) => (
              <DataTable
                columns={columns}
                data={items}
                getRowId={(row) => row.userId}
                searchPlaceholder={t('Search name or email')}
                empty={
                  <EmptyState
                    icon={Users}
                    title={t('No members match')}
                    description={t(
                      'Clear the search to see everyone in the organization.',
                    )}
                  />
                }
              />
            )}
          </QueryBoundary>
        </Card>

        <Card>
          <CardContent className="flex items-start justify-between gap-4">
            <div>
              <Label htmlFor="solo-mode">{t('Solo mode')}</Label>
              <p className="mt-0.5 max-w-xl text-sm text-muted-foreground">
                {t(
                  'Lets the person who created a request also approve it. Use it only when one person runs the treasury: it switches off the maker-checker control.',
                )}
              </p>
            </div>
            <Switch
              id="solo-mode"
              checked={scope.org.soloMode}
              disabled={!scope.can('OWN') || settings.isPending}
              onCheckedChange={(soloMode) =>
                settings.mutate(
                  { soloMode },
                  { onError: (error) => toast.error(errorMessage(error)) },
                )
              }
            />
          </CardContent>
        </Card>
      </div>

      <MemberDialog
        key={`${dialog?.mode}-${dialog?.member?.userId}`}
        mode={dialog?.mode ?? null}
        member={dialog?.member ?? null}
        onClose={() => setDialog(null)}
      />
    </Page>
  );
}
