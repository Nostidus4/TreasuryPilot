import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Check,
  CircleDollarSign,
  LogOut,
  Plus,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';

import { QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Select } from '@/components/ui/controls';
import { Field, Input } from '@/components/ui/input';
import { Alert } from '@/components/ui/misc';
import { useMe, useSignOut } from '@/features/auth/api';
import { useCreateOrg, useOrg } from '@/features/orgs/api';
import { useOrgScope } from '@/features/orgs/org-scope';
import { errorMessage } from '@/lib/api/http';
import { t } from '@/lib/i18n';
import { roleLabels } from '@/lib/status';
import { cn } from '@/lib/utils';

const countries = [
  { value: 'VN', label: 'Vietnam' },
  { value: 'SG', label: 'Singapore' },
  { value: 'US', label: 'United States' },
  { value: 'GB', label: 'United Kingdom' },
];

const timezones = [
  'Asia/Ho_Chi_Minh',
  'Asia/Singapore',
  'Europe/London',
  'America/New_York',
  'UTC',
].map((zone) => ({ value: zone, label: zone.replace('_', ' ') }));

/** Chrome for account-level pages that sit outside any organization. */
export function AccountLayout({ children }: { children: ReactNode }) {
  const me = useMe();
  const signOut = useSignOut();
  const navigate = useNavigate();
  const location = useLocation();
  const home = me.data?.memberships[0];
  // Wallets is reached from inside an org; give it an obvious way back.
  const backToOrg = home && location.pathname !== '/orgs';
  return (
    <div className="min-h-dvh bg-background">
      <header className="flex h-14 items-center gap-3 border-b bg-surface px-4 sm:px-6">
        <Link
          to={home ? `/o/${home.orgId}` : '/orgs'}
          className="flex items-center gap-2.5 text-base font-semibold"
        >
          <span className="grid size-8 place-items-center rounded-md bg-primary text-primary-foreground">
            <CircleDollarSign className="size-4" aria-hidden="true" />
          </span>
          TreasuryPilot
        </Link>
        {backToOrg && (
          <Button asChild variant="ghost" size="sm" className="ml-2">
            <Link to={`/o/${home.orgId}`}>
              <ArrowLeft aria-hidden="true" />
              {t('Back to {{org}}', { org: home.orgName })}
            </Link>
          </Button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden text-sm text-muted-foreground sm:inline">
            {me.data?.user.email}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              signOut.mutate(undefined, {
                onSuccess: () => navigate('/login', { replace: true }),
              })
            }
          >
            <LogOut aria-hidden="true" />
            {t('Sign out')}
          </Button>
        </div>
      </header>
      <main id="main">{children}</main>
    </div>
  );
}

function CreateOrgForm({ first }: { first: boolean }) {
  const navigate = useNavigate();
  const create = useCreateOrg();
  const [name, setName] = useState('');
  const [legalName, setLegalName] = useState('');
  const [country, setCountry] = useState('VN');
  const [displayTz, setDisplayTz] = useState('Asia/Ho_Chi_Minh');
  const nameError = create.isError
    ? (create.error instanceof Error && errorMessage(create.error)) || undefined
    : undefined;

  return (
    <Card>
      <CardHeader
        title={
          first
            ? t('Create your organization')
            : t('Create another organization')
        }
        description={t(
          'An organization holds your members, treasuries and payment requests. You become its admin.',
        )}
      />
      <CardContent>
        <form
          className="grid gap-4 sm:grid-cols-2"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate(
              { name, legalName: legalName || undefined, country, displayTz },
              { onSuccess: ({ org }) => navigate(`/o/${org.id}/onboarding`) },
            );
          }}
        >
          <Field
            htmlFor="org-name"
            label={t('Organization name')}
            error={nameError}
          >
            <Input
              id="org-name"
              required
              value={name}
              aria-invalid={Boolean(nameError)}
              onChange={(event) => setName(event.target.value)}
              placeholder="Northwind Labs"
            />
          </Field>
          <Field htmlFor="org-legal" label={t('Legal name')} optional>
            <Input
              id="org-legal"
              value={legalName}
              onChange={(event) => setLegalName(event.target.value)}
              placeholder="Northwind Labs Pte. Ltd."
            />
          </Field>
          <Field htmlFor="org-country" label={t('Country')}>
            <Select
              id="org-country"
              value={country}
              onValueChange={setCountry}
              options={countries}
            />
          </Field>
          <Field
            htmlFor="org-tz"
            label={t('Display time zone')}
            hint={t(
              'Limits always reset at 00:00 UTC. This only affects how times are shown.',
            )}
          >
            <Select
              id="org-tz"
              value={displayTz}
              onValueChange={setDisplayTz}
              options={timezones}
            />
          </Field>
          <div className="sm:col-span-2">
            <Button type="submit" variant="primary" loading={create.isPending}>
              <Plus aria-hidden="true" />
              {t('Create organization')}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export function OrgsPage() {
  const me = useMe();
  const memberships = me.data?.memberships ?? [];
  return (
    <AccountLayout>
      <Page
        width="narrow"
        title={t('Organizations')}
        description={
          memberships.length > 0
            ? t('Choose an organization to work in, or create a new one.')
            : t(
                'You are not a member of an organization yet. Create one to get started.',
              )
        }
      >
        <div className="grid gap-6">
          {memberships.length > 0 && (
            <Card>
              <ul className="divide-y">
                {memberships.map((membership) => (
                  <li key={membership.orgId}>
                    <Link
                      to={`/o/${membership.orgId}`}
                      className="flex items-center gap-3 px-4 py-3 hover:bg-surface-muted"
                    >
                      <span className="grid size-9 place-items-center rounded-md border bg-surface-muted text-muted-foreground">
                        <Building2 className="size-4" aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-base font-medium">
                          {membership.orgName}
                        </span>
                        <span className="mt-1 flex flex-wrap gap-1">
                          {membership.roles.map((role) => (
                            <Badge key={role}>{t(roleLabels[role])}</Badge>
                          ))}
                        </span>
                      </span>
                      <ArrowRight
                        className="size-4 text-subtle-foreground"
                        aria-hidden="true"
                      />
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <CreateOrgForm first={memberships.length === 0} />
        </div>
      </Page>
    </AccountLayout>
  );
}

/** `/o/:org`: the checklist with no treasury, the dashboard with one, else the portfolio. */
export function OrgIndexRedirect({ children }: { children: ReactNode }) {
  const scope = useOrgScope();
  if (scope.org.treasuries.length <= 1) {
    return <Navigate to={scope.tBase} replace />;
  }
  return children;
}

/** Onboarding checklist (WEB-002): every item and its state come from the API. */
export function OnboardingPage() {
  const scope = useOrgScope();
  const query = useOrg(scope.orgId);
  return (
    <Page
      width="narrow"
      title={t('Set up {{name}}', { name: scope.org.name })}
      description={t(
        'Five steps before the agent can pay an invoice. Each one is a control you own.',
      )}
    >
      <QueryBoundary query={query}>
        {({ checklist }) => {
          const done = checklist.filter((item) => item.done).length;
          const next = checklist.find((item) => !item.done);
          return (
            <div className="grid gap-4">
              <div>
                <div className="flex items-baseline justify-between text-sm">
                  <span className="font-medium">
                    {t('{{done}} of {{total}} complete', {
                      done,
                      total: checklist.length,
                    })}
                  </span>
                </div>
                <div
                  className="mt-2 flex gap-1"
                  role="progressbar"
                  aria-label={t('Setup progress')}
                  aria-valuemin={0}
                  aria-valuemax={checklist.length}
                  aria-valuenow={done}
                >
                  {checklist.map((item) => (
                    <span
                      key={item.key}
                      className={cn(
                        'h-1.5 flex-1 rounded-full',
                        item.done ? 'bg-success' : 'bg-border-strong',
                      )}
                    />
                  ))}
                </div>
              </div>
              {!next && (
                <Alert tone="success" title={t('Setup complete')}>
                  {t('The treasury is ready to operate.')}{' '}
                  <Link className="font-medium underline" to={scope.tBase}>
                    {t('Open the overview')}
                  </Link>
                </Alert>
              )}
              <Card>
                <ol className="divide-y">
                  {checklist.map((item, index) => (
                    <li key={item.key} className="flex items-start gap-3 p-4">
                      <span
                        className={cn(
                          'num mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border text-xs font-medium',
                          item.done
                            ? 'border-success bg-success text-white'
                            : 'border-border-strong text-muted-foreground',
                        )}
                      >
                        {item.done ? (
                          <Check className="size-3.5" aria-hidden="true" />
                        ) : (
                          index + 1
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-base font-medium">
                          {t(item.title)}
                          {item.done && (
                            <span className="sr-only"> — {t('done')}</span>
                          )}
                        </p>
                        <p className="mt-0.5 text-sm text-muted-foreground">
                          {t(item.description)}
                        </p>
                      </div>
                      <Button
                        asChild
                        size="sm"
                        variant={item === next ? 'primary' : 'secondary'}
                      >
                        <Link to={item.href}>
                          {item.done ? t('Review') : t('Start')}
                        </Link>
                      </Button>
                    </li>
                  ))}
                </ol>
              </Card>
            </div>
          );
        }}
      </QueryBoundary>
    </Page>
  );
}
