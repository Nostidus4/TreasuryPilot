import { Check, RotateCw } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { decodeEventLog, parseAbi } from 'viem';
import { usePublicClient } from 'wagmi';

import { Address } from '@/components/domain/chain';
import { KeyValueList } from '@/components/domain/display';
import { DecodedCalls } from '@/components/domain/signing';
import { QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from '@/components/ui/card';
import { Select } from '@/components/ui/controls';
import { Field, Input, Textarea } from '@/components/ui/input';
import { Alert, Skeleton } from '@/components/ui/misc';
import { useGovernanceTx } from '@/features/controls/api';
import { GovernanceActions } from '@/features/governance/governance-detail';
import { useOrgScope } from '@/features/orgs/org-scope';
import {
  useAcknowledgeCoverage,
  useCreateTreasury,
  useDeployModuleTx,
  useRefreshCoverage,
  useSafeDeploymentTx,
  useSetGuardian,
  useTreasury,
  type TreasuryInput,
} from '@/features/treasury/api';
import { useChains } from '@/lib/api/chains';
import { errorMessage, isApiError } from '@/lib/api/http';
import type { TreasuryState } from '@/lib/api/types';
import { mockApiEnabled } from '@/lib/env';
import { t } from '@/lib/i18n';
import { cn } from '@/lib/utils';
import { useWallet } from '@/lib/wallet/wallet-context';

const safeFactoryAbi = parseAbi([
  'event ProxyCreation(address indexed proxy, address singleton)',
]);

const steps = [
  {
    title: 'Chain and asset',
    detail: 'Where the treasury lives and what it pays in.',
  },
  { title: 'Safes', detail: 'The Safes that hold the funds.' },
  {
    title: 'Module',
    detail: 'Enable the TreasuryPilot module with a Safe transaction.',
  },
  { title: 'Coverage', detail: 'Check that nothing else can move the funds.' },
  { title: 'Guardian Safe', detail: 'Who can pause in an emergency.' },
] as const;

const draftKey = (orgId: string) => `treasurypilot.setup-draft.${orgId}`;

interface Draft {
  name: string;
  chainId: number;
  assetId: string;
  safes: Record<'T' | 'O1' | 'O2', string>;
}

function readDraft(orgId: string): Partial<Draft> {
  try {
    return JSON.parse(
      window.sessionStorage.getItem(draftKey(orgId)) ?? '{}',
    ) as Partial<Draft>;
  } catch {
    return {};
  }
}

const safeRoles: Array<{
  role: 'T' | 'O1' | 'O2';
  label: string;
  hint: string;
  optional?: boolean;
}> = [
  {
    role: 'T',
    label: 'Treasury Safe',
    hint: 'Holds reserves. Its owners sign every governance transaction.',
  },
  {
    role: 'O1',
    label: 'Payments Safe',
    hint: 'Invoices are paid from here. Refilled from the Treasury Safe.',
  },
  {
    role: 'O2',
    label: 'Second operational Safe',
    hint: 'For example payroll.',
    optional: true,
  },
];

function Stepper({ current }: { current: number }) {
  return (
    <ol className="grid gap-1" aria-label={t('Setup steps')}>
      {steps.map((step, index) => {
        const done = index < current;
        const active = index === current;
        return (
          <li
            key={step.title}
            aria-current={active ? 'step' : undefined}
            className={cn(
              'flex gap-3 rounded-md px-2 py-2',
              active && 'bg-surface-muted',
            )}
          >
            <span
              className={cn(
                'num mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border text-xs font-medium',
                done && 'border-success bg-success text-white',
                active && 'border-primary text-foreground',
                !done &&
                  !active &&
                  'border-border-strong text-subtle-foreground',
              )}
            >
              {done ? (
                <Check className="size-3.5" aria-hidden="true" />
              ) : (
                index + 1
              )}
            </span>
            <span>
              <span
                className={cn(
                  'block text-base',
                  active ? 'font-medium' : done ? '' : 'text-muted-foreground',
                )}
              >
                {t(step.title)}
                {done && <span className="sr-only"> — {t('done')}</span>}
              </span>
              <span className="block text-xs text-muted-foreground">
                {t(step.detail)}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** Steps 1–2 only live in the browser until the treasury is created. */
function CreateSteps({ onCreated }: { onCreated: (id: string) => void }) {
  const scope = useOrgScope();
  const chains = useChains();
  const create = useCreateTreasury(scope.orgId);
  const deploySafe = useSafeDeploymentTx(scope.orgId);
  const wallet = useWallet();
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Draft>(() => ({
    name: 'Operating treasury',
    chainId: 0,
    assetId: '',
    safes: { T: '', O1: '', O2: '' },
    ...readDraft(scope.orgId),
  }));
  const [formError, setFormError] = useState<Record<string, string>>({});
  const [safeOwners, setSafeOwners] = useState('');
  const [safeThreshold, setSafeThreshold] = useState('1');
  const [safeTargetRole, setSafeTargetRole] = useState<'T' | 'O1' | 'O2'>('T');
  const [deployError, setDeployError] = useState('');
  const publicClient = usePublicClient({
    chainId: draft.chainId || 11155111,
  });

  useEffect(() => {
    try {
      window.sessionStorage.setItem(
        draftKey(scope.orgId),
        JSON.stringify(draft),
      );
    } catch {
      /* the draft lasts for this page only */
    }
  }, [draft, scope.orgId]);

  const serverErrors = isApiError(create.error)
    ? Object.fromEntries(
        (create.error.problem.errors ?? []).map((item) => [
          item.field,
          item.message,
        ]),
      )
    : {};
  const errorFor = (key: string) => formError[key] ?? serverErrors[key];

  const submit = () => {
    const errors: Record<string, string> = {};
    for (const { role, optional } of safeRoles) {
      const value = draft.safes[role].trim();
      if (!value && optional) continue;
      if (!/^0x[0-9a-fA-F]{40}$/.test(value)) {
        errors[`wallets.${role}`] = t(
          'Enter a 0x address with 40 hex characters.',
        );
      }
    }
    setFormError(errors);
    if (Object.keys(errors).length > 0) return;
    const input: TreasuryInput = {
      name: draft.name,
      chainId: draft.chainId,
      assetId: draft.assetId,
      wallets: safeRoles
        .filter(({ role }) => draft.safes[role].trim())
        .map(({ role, label }) => ({
          role: role,
          safeAddress: draft.safes[role].trim(),
          label,
        })),
    };
    create.mutate(input, {
      onSuccess: ({ treasury }) => {
        try {
          window.sessionStorage.removeItem(draftKey(scope.orgId));
        } catch {
          /* nothing to clear */
        }
        onCreated(treasury.id);
      },
    });
  };

  const createSafe = async (role: 'T' | 'O1' | 'O2') => {
    setDeployError('');
    const owners = safeOwners
      .split(/[\s,]+/)
      .map((owner) => owner.trim())
      .filter(Boolean);
    const threshold = Number(safeThreshold);
    if (
      owners.length === 0 ||
      owners.some((owner) => !/^0x[0-9a-fA-F]{40}$/.test(owner)) ||
      new Set(owners.map((owner) => owner.toLowerCase())).size !==
        owners.length ||
      !Number.isInteger(threshold) ||
      threshold < 1 ||
      threshold > owners.length
    ) {
      setDeployError(
        t(
          'Enter distinct owner addresses and a threshold from 1 to the owner count.',
        ),
      );
      return;
    }
    if (!wallet.address) {
      setDeployError(
        t('Connect a wallet to submit the Safe deployment transaction.'),
      );
      return;
    }
    try {
      const result = await deploySafe.mutateAsync({
        chainId: draft.chainId,
        owners,
        threshold,
      });
      if (wallet.chainId !== draft.chainId)
        await wallet.switchChain(draft.chainId);
      const hash = await wallet.sendTransaction({
        to: result.transaction.to,
        data: result.transaction.data,
        value: result.transaction.value,
        chainId: draft.chainId,
      });
      if (!publicClient)
        throw new Error(t('No RPC client is available for this chain.'));
      const receipt = await publicClient.waitForTransactionReceipt({ hash });
      if (receipt.status !== 'success') {
        throw new Error(
          t('The Safe deployment transaction reverted. Transaction: {{hash}}', {
            hash,
          }),
        );
      }
      const factory = result.transaction.to.toLowerCase();
      const event = receipt.logs.find((log) => {
        if (log.address.toLowerCase() !== factory) return false;
        try {
          decodeEventLog({
            abi: safeFactoryAbi,
            data: log.data,
            topics: log.topics,
          });
          return true;
        } catch {
          return false;
        }
      });
      if (!event) {
        throw new Error(
          t(
            'The transaction was mined, but no Safe address was returned. Transaction: {{hash}}',
            {
              hash,
            },
          ),
        );
      }
      const decoded = decodeEventLog({
        abi: safeFactoryAbi,
        data: event.data,
        topics: event.topics,
      });
      // Functional update: the draft may have been edited while the wallet prompt and receipt wait ran.
      setDraft((current) => ({
        ...current,
        safes: { ...current.safes, [role]: decoded.args.proxy },
      }));
    } catch (error) {
      setDeployError(
        error instanceof Error ? error.message : t('Safe deployment failed.'),
      );
    }
  };

  const summaryChain =
    chains.data?.find((item) => item.chainId === draft.chainId) ??
    chains.data?.[0];
  const summaryAsset =
    summaryChain?.assets.find((asset) => asset.id === draft.assetId) ??
    summaryChain?.assets[0];
  const summary: SetupSummaryData = {
    name: draft.name.trim(),
    chain: summaryChain?.name,
    asset:
      summaryAsset &&
      (summaryAsset.isTest
        ? `${summaryAsset.symbol} (${t('test asset')})`
        : summaryAsset.symbol),
    safes: safeRoles.map(({ role, label }) => ({
      role,
      label,
      address: /^0x[0-9a-fA-F]{40}$/.test(draft.safes[role].trim())
        ? draft.safes[role].trim()
        : undefined,
    })),
  };

  return (
    <Layout current={step} summary={summary}>
      <QueryBoundary query={chains}>
        {(items) => {
          const chain =
            items.find((item) => item.chainId === draft.chainId) ?? items[0];
          const assetId = draft.assetId || chain?.assets[0]?.id || '';
          const chainId = draft.chainId || chain?.chainId || 0;
          if (step === 0) {
            return (
              <Card>
                <CardHeader
                  title={t('Chain and asset')}
                  description={t(steps[0].detail)}
                />
                <CardContent className="grid gap-4">
                  <Field htmlFor="treasury-name" label={t('Treasury name')}>
                    <Input
                      id="treasury-name"
                      value={draft.name}
                      onChange={(event) =>
                        setDraft({ ...draft, name: event.target.value })
                      }
                    />
                  </Field>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field htmlFor="treasury-chain" label={t('Chain')}>
                      <Select
                        id="treasury-chain"
                        value={String(chainId)}
                        onValueChange={(value) =>
                          setDraft({
                            ...draft,
                            chainId: Number(value),
                            assetId: '',
                          })
                        }
                        options={items.map((item) => ({
                          value: String(item.chainId),
                          label: item.name,
                        }))}
                      />
                    </Field>
                    <Field htmlFor="treasury-asset" label={t('Payment asset')}>
                      <Select
                        id="treasury-asset"
                        value={assetId}
                        onValueChange={(value) =>
                          setDraft({ ...draft, assetId: value })
                        }
                        options={(chain?.assets ?? []).map((asset) => ({
                          value: asset.id,
                          label: asset.isTest
                            ? `${asset.symbol} (${t('test asset')})`
                            : asset.symbol,
                        }))}
                      />
                    </Field>
                  </div>
                  {chain?.assets.find((asset) => asset.id === assetId)
                    ?.isTest && (
                    <Alert tone="warning" title={t('Test network')}>
                      {t(
                        '{{chain}} is a testnet. Amounts shown in this treasury have no real value and are labelled TEST.',
                        { chain: chain.name },
                      )}
                    </Alert>
                  )}
                </CardContent>
                <CardFooter>
                  <Button
                    variant="primary"
                    disabled={!draft.name.trim()}
                    onClick={() => {
                      setDraft({ ...draft, chainId, assetId });
                      setStep(1);
                    }}
                  >
                    {t('Continue')}
                  </Button>
                </CardFooter>
              </Card>
            );
          }
          return (
            <Card>
              <CardHeader
                title={t('Safes')}
                description={t(
                  'Paste the addresses of Safes on {{chain}}. TreasuryPilot never owns a Safe.',
                  { chain: chain?.name ?? '' },
                )}
                action={
                  mockApiEnabled && (
                    <Button
                      size="sm"
                      onClick={() =>
                        setDraft({
                          ...draft,
                          safes: {
                            T: '0x1111111111111111111111111111111111111aa1',
                            O1: '0x2222222222222222222222222222222222222bb2',
                            O2: '',
                          },
                        })
                      }
                    >
                      {t('Use demo Safes')}
                    </Button>
                  )
                }
              />
              <CardContent className="grid gap-4">
                {chain && !chain.safeDeploymentAvailable && (
                  <Alert
                    tone="warning"
                    title={t('Safe deployment unavailable')}
                  >
                    {t(
                      'Creating a Safe from this screen is unavailable on {{chain}} because its verified Safe factory, v1.4.1 singleton, and fallback handler are not configured. You can continue with Safes that already exist on this chain.',
                      { chain: chain.name },
                    )}
                  </Alert>
                )}
                {chain?.safeDeploymentAvailable && (
                  <section className="grid gap-3 rounded-md border border-border p-4">
                    <div>
                      <h3 className="font-medium">{t('Create a Safe')}</h3>
                      <p className="text-sm text-muted-foreground">
                        {t(
                          'The transaction is sent by your connected wallet. TreasuryPilot never receives keys or signs for you.',
                        )}
                      </p>
                    </div>
                    <Field
                      htmlFor="safe-owners"
                      label={t('Safe owners')}
                      hint={t('Enter one 0x address per line.')}
                    >
                      <Textarea
                        id="safe-owners"
                        value={safeOwners}
                        onChange={(event) => setSafeOwners(event.target.value)}
                        placeholder="0x…"
                      />
                    </Field>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field
                        htmlFor="safe-threshold"
                        label={t('Signing threshold')}
                      >
                        <Input
                          id="safe-threshold"
                          inputMode="numeric"
                          type="number"
                          min={1}
                          value={safeThreshold}
                          onChange={(event) =>
                            setSafeThreshold(event.target.value)
                          }
                        />
                      </Field>
                      <Field
                        htmlFor="safe-target-role"
                        label={t('Use this Safe for')}
                      >
                        <Select
                          id="safe-target-role"
                          value={safeTargetRole}
                          onValueChange={(value) =>
                            setSafeTargetRole(value as 'T' | 'O1' | 'O2')
                          }
                          options={safeRoles.map(({ role, label }) => ({
                            value: role,
                            label: t(label),
                          }))}
                        />
                      </Field>
                    </div>
                    {deployError && <Alert tone="danger">{deployError}</Alert>}
                    <div>
                      <Button
                        variant="secondary"
                        loading={deploySafe.isPending}
                        disabled={!draft.chainId}
                        onClick={() => void createSafe(safeTargetRole)}
                      >
                        {t('Create Safe and add address')}
                      </Button>
                    </div>
                  </section>
                )}
                {safeRoles.map(({ role, label, hint, optional }) => (
                  <Field
                    key={role}
                    htmlFor={`safe-${role}`}
                    label={`${t(label)} (${role})`}
                    hint={t(hint)}
                    optional={optional}
                    error={errorFor(`wallets.${role}`)}
                  >
                    <Input
                      id={`safe-${role}`}
                      className="num"
                      placeholder="0x…"
                      value={draft.safes[role]}
                      aria-invalid={Boolean(errorFor(`wallets.${role}`))}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          safes: { ...draft.safes, [role]: event.target.value },
                        })
                      }
                    />
                  </Field>
                ))}
                {create.isError && Object.keys(serverErrors).length === 0 && (
                  <Alert tone="danger">{errorMessage(create.error)}</Alert>
                )}
              </CardContent>
              <CardFooter>
                <Button variant="ghost" onClick={() => setStep(0)}>
                  {t('Back')}
                </Button>
                <Button
                  variant="primary"
                  loading={create.isPending}
                  onClick={submit}
                >
                  {t('Check Safes and continue')}
                </Button>
              </CardFooter>
            </Card>
          );
        }}
      </QueryBoundary>
    </Layout>
  );
}

function ModuleStep({
  onDone,
  state,
}: {
  onDone: () => void;
  state: TreasuryState;
}) {
  const scope = useOrgScope();
  const deploy = useDeployModuleTx(scope.orgId);
  const [txId, setTxId] = useState<string>();
  const tx = useGovernanceTx(scope.orgId, txId);
  const treasuryId = state.treasury.id;
  const { mutate } = deploy;

  useEffect(() => {
    mutate(treasuryId, {
      onSuccess: ({ governanceTx }) => setTxId(governanceTx.id),
    });
  }, [mutate, treasuryId]);

  const executed = tx.data?.governanceTx.status === 'Executed';
  return (
    <Card>
      <CardHeader
        title={t('Enable the module')}
        description={t(
          'The module is the on-chain component that enforces the mandate. Enabling it is a transaction of your Treasury Safe: sign it, then execute it.',
        )}
      />
      <CardContent className="grid gap-4">
        {deploy.isError && (
          <Alert tone="danger">{errorMessage(deploy.error)}</Alert>
        )}
        {!tx.data ? (
          <Skeleton className="h-48" />
        ) : (
          <>
            <DecodedCalls calls={tx.data.governanceTx.calls} />
            <GovernanceActions
              tx={tx.data.governanceTx}
              typedData={tx.data.typedData}
            />
          </>
        )}
      </CardContent>
      <CardFooter>
        <Button variant="primary" disabled={!executed} onClick={onDone}>
          {t('Continue')}
        </Button>
      </CardFooter>
    </Card>
  );
}

function CoverageStep({
  onDone,
  state,
}: {
  onDone: () => void;
  state: TreasuryState;
}) {
  const scope = useOrgScope();
  const refresh = useRefreshCoverage(scope.orgId);
  const acknowledge = useAcknowledgeCoverage(scope.orgId);
  const [reason, setReason] = useState('');
  const { coverage, treasury } = state;
  const { mutate } = refresh;

  useEffect(() => {
    if (coverage.status === 'UNKNOWN') mutate(treasury.id);
  }, [coverage.status, mutate, treasury.id]);

  const ok = coverage.status === 'COMPLETE' || coverage.acknowledged;
  return (
    <Card>
      <CardHeader
        title={t('Coverage check')}
        description={t(
          'TreasuryPilot reads every Safe’s modules, guard and fallback handler. Coverage is complete when the mandate is the only way funds can move.',
        )}
        action={
          <Button
            size="sm"
            loading={refresh.isPending}
            onClick={() => mutate(treasury.id)}
          >
            <RotateCw aria-hidden="true" />
            {t('Check again')}
          </Button>
        }
      />
      <CardContent className="grid gap-4">
        {refresh.isError && (
          <Alert tone="danger">{errorMessage(refresh.error)}</Alert>
        )}
        {coverage.status === 'UNKNOWN' && !refresh.isError && (
          <Skeleton className="h-20" />
        )}
        {coverage.status === 'COMPLETE' && (
          <Alert tone="success" title={t('Coverage is complete')}>
            <ul className="list-disc pl-4">
              {coverage.details.map((detail) => (
                <li key={detail}>{detail}</li>
              ))}
            </ul>
          </Alert>
        )}
        {coverage.status === 'PARTIAL' && (
          <>
            <Alert tone="warning" title={t('Coverage is partial')}>
              <ul className="list-disc pl-4">
                {coverage.details.map((detail) => (
                  <li key={detail}>{detail}</li>
                ))}
              </ul>
            </Alert>
            {coverage.acknowledged ? (
              <Alert tone="neutral">
                {t(
                  'You accepted partial coverage. A banner will stay visible on every page.',
                )}
              </Alert>
            ) : (
              <form
                className="grid gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  acknowledge.mutate({ treasuryId: treasury.id, reason });
                }}
              >
                <p className="text-sm text-muted-foreground">
                  {t(
                    'Best: remove the other module in Safe{Wallet}, then check again. To continue anyway, record why partial coverage is acceptable.',
                  )}
                </p>
                <Field
                  htmlFor="coverage-reason"
                  label={t('Reason for accepting partial coverage')}
                  error={
                    acknowledge.isError
                      ? errorMessage(acknowledge.error)
                      : undefined
                  }
                >
                  <Textarea
                    id="coverage-reason"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                  />
                </Field>
                <Button
                  type="submit"
                  className="justify-self-start"
                  loading={acknowledge.isPending}
                  disabled={!reason.trim()}
                >
                  {t('Accept partial coverage')}
                </Button>
              </form>
            )}
          </>
        )}
      </CardContent>
      <CardFooter>
        <Button variant="primary" disabled={!ok} onClick={onDone}>
          {t('Continue')}
        </Button>
      </CardFooter>
    </Card>
  );
}

function GuardianStep({ state }: { state: TreasuryState }) {
  const scope = useOrgScope();
  const navigate = useNavigate();
  const setGuardian = useSetGuardian(scope.orgId);
  const [address, setAddress] = useState('');
  return (
    <Card>
      <CardHeader
        title={t('Guardian Safe')}
        description={t(
          'The Guardian can pause the treasury at any time but can never move funds or resume. Use a Safe whose owners can react quickly.',
        )}
      />
      <CardContent>
        <form
          id="guardian-form"
          onSubmit={(event) => {
            event.preventDefault();
            setGuardian.mutate(
              { treasuryId: state.treasury.id, safeAddress: address.trim() },
              {
                onSuccess: () =>
                  navigate(`${scope.base}/t/${state.treasury.id}/mandate`),
              },
            );
          }}
        >
          <Field
            htmlFor="guardian-address"
            label={t('Guardian Safe address')}
            error={
              setGuardian.isError ? errorMessage(setGuardian.error) : undefined
            }
            hint={t(
              'Next you will define the mandate: limits, buffers and approvers.',
            )}
          >
            <Input
              id="guardian-address"
              className="num"
              placeholder="0x…"
              value={address}
              aria-invalid={setGuardian.isError}
              onChange={(event) => setAddress(event.target.value)}
            />
          </Field>
        </form>
      </CardContent>
      <CardFooter>
        {mockApiEnabled && (
          <Button
            className="mr-auto"
            size="sm"
            onClick={() =>
              setAddress('0x3333333333333333333333333333333333333cc3')
            }
          >
            {t('Use demo Safe')}
          </Button>
        )}
        <Button
          type="submit"
          form="guardian-form"
          variant="primary"
          loading={setGuardian.isPending}
        >
          {t('Finish setup')}
        </Button>
      </CardFooter>
    </Card>
  );
}

interface SetupSummaryData {
  name: string;
  chain?: string;
  asset?: string;
  safes: Array<{ role: string; label: string; address?: string }>;
  module?: string;
  coverage?: string;
  guardian?: string;
}

function Pending() {
  return <span className="text-subtle-foreground">{t('Not set')}</span>;
}

/** What has been decided so far, so each step can be checked in context. */
function SetupSummary({ data }: { data: SetupSummaryData }) {
  return (
    <Card>
      <CardHeader
        title={t('Summary')}
        description={t(
          'Updates as you go. Nothing is on-chain until you sign.',
        )}
      />
      <CardContent className="grid gap-4">
        <KeyValueList
          items={[
            { label: t('Name'), value: data.name || <Pending /> },
            { label: t('Chain'), value: data.chain ?? <Pending /> },
            { label: t('Asset'), value: data.asset ?? <Pending /> },
          ]}
        />
        <KeyValueList
          items={data.safes.map((safe) => ({
            label: `${t(safe.label)} (${safe.role})`,
            value: safe.address ? (
              <Address address={safe.address} />
            ) : (
              <Pending />
            ),
          }))}
        />
        <KeyValueList
          items={[
            { label: t('Module'), value: data.module ?? <Pending /> },
            { label: t('Coverage'), value: data.coverage ?? <Pending /> },
            {
              label: t('Guardian Safe'),
              value: data.guardian ? (
                <Address address={data.guardian} />
              ) : (
                <Pending />
              ),
            },
          ]}
        />
      </CardContent>
    </Card>
  );
}

function Layout({
  children,
  current,
  summary,
}: {
  children: ReactNode;
  current: number;
  summary: SetupSummaryData;
}) {
  return (
    <div className="grid items-start gap-6 md:grid-cols-[16rem_minmax(0,1fr)] xl:grid-cols-[16rem_minmax(0,1fr)_20rem]">
      <Card className="p-2 md:sticky md:top-[4.5rem]">
        <Stepper current={current} />
      </Card>
      <div className="grid gap-3">
        <Badge className="w-fit">
          {t('Step {{current}} of {{total}}', {
            current: current + 1,
            total: steps.length,
          })}
        </Badge>
        {children}
      </div>
      <aside className="md:col-start-2 xl:sticky xl:top-[4.5rem] xl:col-start-3 xl:row-start-1">
        <SetupSummary data={summary} />
      </aside>
    </div>
  );
}

/** Steps 3–5 resume from server state, so a reload never loses progress. */
function ResumeSteps({ treasuryId }: { treasuryId: string }) {
  const scope = useOrgScope();
  const query = useTreasury(scope.orgId, treasuryId);
  const [stage, setStage] = useState<number>();
  return (
    <QueryBoundary query={query}>
      {(state) => {
        const derived =
          state.coverage.status === 'UNKNOWN'
            ? 2
            : state.coverage.status === 'COMPLETE' ||
                state.coverage.acknowledged
              ? 4
              : 3;
        const current = stage ?? derived;
        const guardian = state.wallets.find(
          (wallet) => wallet.role === 'GUARDIAN',
        );
        const summary: SetupSummaryData = {
          name: state.treasury.name,
          chain: state.treasury.chainName,
          asset: state.treasury.asset.isTest
            ? `${state.treasury.asset.symbol} (${t('test asset')})`
            : state.treasury.asset.symbol,
          safes: safeRoles.map(({ role, label }) => ({
            role,
            label,
            address: state.wallets.find((wallet) => wallet.role === role)
              ?.safeAddress,
          })),
          module:
            state.coverage.status === 'UNKNOWN'
              ? t('Waiting for owner signatures')
              : t('Enabled'),
          coverage:
            state.coverage.status === 'UNKNOWN'
              ? undefined
              : state.coverage.status === 'COMPLETE'
                ? t('Complete')
                : state.coverage.acknowledged
                  ? t('Partial, acknowledged')
                  : t('Partial'),
          guardian: guardian?.safeAddress,
        };
        return (
          <Layout current={current} summary={summary}>
            {current === 2 && (
              <ModuleStep state={state} onDone={() => setStage(3)} />
            )}
            {current === 3 && (
              <CoverageStep state={state} onDone={() => setStage(4)} />
            )}
            {current === 4 && <GuardianStep state={state} />}
          </Layout>
        );
      }}
    </QueryBoundary>
  );
}

/** Treasury setup wizard (WEB-004). */
export function SetupWizardPage() {
  const scope = useOrgScope();
  const [params, setParams] = useSearchParams();
  const treasuryId = params.get('t');
  const allowed = scope.can('OWN', 'ADM');

  return (
    <Page
      width="wide"
      title={t('Set up a treasury')}
      description={t(
        'Connect your Safes and put the on-chain controls in place. Nothing here gives TreasuryPilot custody of your funds.',
      )}
    >
      {!allowed ? (
        <Alert tone="warning" title={t('Owner or admin role needed')}>
          {t(
            'Ask an organization admin to set up the treasury or grant you the role.',
          )}
        </Alert>
      ) : treasuryId ? (
        <ResumeSteps treasuryId={treasuryId} />
      ) : (
        <CreateSteps
          onCreated={(id) => setParams({ t: id }, { replace: true })}
        />
      )}
    </Page>
  );
}
