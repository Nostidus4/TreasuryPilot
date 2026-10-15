import { Check, RotateCw } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { decodeEventLog, isAddress, parseAbi } from 'viem';
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
import { useGovernanceTx, useGovernanceTxs } from '@/features/controls/api';
import { GovernanceActions } from '@/features/governance/governance-detail';
import { useOrgScope } from '@/features/orgs/org-scope';
import {
  useAcknowledgeCoverage,
  useCreateTreasury,
  useDeployModuleTx,
  useRefreshCoverage,
  useSafeDeploymentTx,
  useTreasurySetup,
  type ModuleSetupInput,
  type TreasuryInput,
} from '@/features/treasury/api';
import { useChains } from '@/lib/api/chains';
import { errorMessage, isApiError } from '@/lib/api/http';
import type { Chain, TreasuryState } from '@/lib/api/types';
import { mockApiEnabled } from '@/lib/env';
import { assetLabel } from '@/lib/format';
import { t } from '@/lib/i18n';
import { cn } from '@/lib/utils';
import { useWallet } from '@/lib/wallet/wallet-context';
import { parseUnits } from '@/lib/money';

const safeFactoryAbi = parseAbi([
  'event ProxyCreation(address indexed proxy, address singleton)',
]);

/** Flip once MDT-010 can deploy and verify the Guardian Safe. */
const GUARDIAN_VERIFICATION_AVAILABLE: boolean = false;

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
  {
    title: 'Guardian Safe',
    detail: GUARDIAN_VERIFICATION_AVAILABLE
      ? 'Who can pause in an emergency.'
      : 'Setup is pending until Sentinel verification is available.',
  },
] as const;

const draftKey = (orgId: string) => `treasurypilot.setup-draft.${orgId}`;
const moduleDraftKey = (treasuryId: string) =>
  `treasurypilot.module-draft.${treasuryId}`;

interface Draft {
  name: string;
  chainId: number;
  assetId: string;
  safes: Record<'T' | 'O1' | 'O2', string>;
}

interface ModuleDraft {
  executor: string;
  guardian: string;
  approvers: string;
  payPerRequest: string;
  payDaily: string;
  refillPerRequest: string;
  refillDaily: string;
  supplyPerRequest: string;
  supplyDaily: string;
  approvalMaxAgeDays: string;
  payeeCoolingSeconds: string;
  expiresInDays: string;
  buffers: Record<string, { minimum: string; target: string }>;
}

function defaultModuleDraft(roles: string[], executor = ''): ModuleDraft {
  return {
    executor,
    guardian: '',
    approvers: executor,
    payPerRequest: '2000',
    payDaily: '10000',
    refillPerRequest: '2500',
    refillDaily: '12000',
    supplyPerRequest: '0',
    supplyDaily: '0',
    approvalMaxAgeDays: '14',
    payeeCoolingSeconds: '300',
    expiresInDays: '30',
    buffers: Object.fromEntries(
      roles.map((role) => [
        role,
        role === 'T'
          ? { minimum: '0', target: '1000' }
          : { minimum: '10', target: '150' },
      ]),
    ),
  };
}

/** A network whose assets are all test assets: drives the option label and the warning. */
const isTestChain = (chain: Chain) =>
  chain.assets.length > 0 && chain.assets.every((asset) => asset.isTest);

function readModuleDraft(treasuryId: string): Partial<ModuleDraft> {
  try {
    return JSON.parse(
      window.sessionStorage.getItem(moduleDraftKey(treasuryId)) ?? '{}',
    ) as Partial<ModuleDraft>;
  } catch {
    return {};
  }
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
    const threshold = /^\d+$/.test(safeThreshold.trim())
      ? Number(safeThreshold)
      : NaN;
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
    asset: summaryAsset && assetLabel(summaryAsset),
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
                          label: isTestChain(item)
                            ? `${item.name} · TEST`
                            : item.name,
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
                          label: assetLabel(asset),
                        }))}
                      />
                    </Field>
                  </div>
                  {chain && isTestChain(chain) && (
                    <Alert tone="warning" title={t('Test network')}>
                      {t(
                        '{{chain}} is a test network. Amounts shown in this treasury have no real value. Its assets are labelled TEST.',
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
  const governance = useGovernanceTxs(scope.orgId);
  const wallet = useWallet();
  const treasuryId = state.treasury.id;
  const treasuryWallets = state.wallets.filter((item) =>
    ['T', 'O1', 'O2'].includes(item.role),
  );
  const initialDraft = defaultModuleDraft(
    treasuryWallets.map((item) => item.role),
    wallet.address ?? '',
  );
  const persistedDraft = readModuleDraft(treasuryId);
  const [draft, setDraft] = useState<ModuleDraft>(() => ({
    ...initialDraft,
    ...persistedDraft,
    buffers: { ...initialDraft.buffers, ...persistedDraft.buffers },
  }));
  const [formError, setFormError] = useState('');
  // An empty persisted value means the wallet was not connected yet, so fill it once it is.
  useEffect(() => {
    const connected = wallet.address;
    if (!connected) return;
    setDraft((current) => ({
      ...current,
      executor: current.executor || connected,
      approvers: current.approvers || connected,
    }));
  }, [wallet.address]);
  useEffect(() => {
    try {
      window.sessionStorage.setItem(
        moduleDraftKey(treasuryId),
        JSON.stringify(draft),
      );
    } catch {
      /* keep the draft for this page only */
    }
  }, [draft, treasuryId]);

  const moduleTxs = (governance.data?.items ?? []).filter(
    (item) => item.treasuryId === treasuryId && item.kind === 'DEPLOY_MODULE',
  );
  const txsBySafe = treasuryWallets.map((safe) =>
    moduleTxs.find(
      (item) => item.safeAddress.toLowerCase() === safe.safeAddress.toLowerCase(),
    ),
  );
  const hasPreparedTransactions =
    txsBySafe.length > 0 && txsBySafe.every(Boolean);
  const hasPartialTransactions =
    !hasPreparedTransactions && txsBySafe.some(Boolean);
  const executed =
    txsBySafe.length > 0 &&
    txsBySafe.every((item) => item?.status === 'Executed');

  const prepare = async () => {
    setFormError('');
    const addressPattern = /^0x[0-9a-fA-F]{40}$/;
    const nonzeroAddress = (value: string) =>
      addressPattern.test(value) && !/^0x0{40}$/i.test(value);
    const approvers = draft.approvers
      .split(/[\s,]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!nonzeroAddress(draft.executor.trim())) {
      setFormError(t('Enter the configured executor address.'));
      return;
    }
    if (!nonzeroAddress(draft.guardian.trim())) {
      setFormError(t('Enter the Guardian Safe address.'));
      return;
    }
    if (
      approvers.length === 0 ||
      approvers.some((item) => !nonzeroAddress(item)) ||
      new Set(approvers.map((item) => item.toLowerCase())).size !==
        approvers.length
    ) {
      setFormError(t('Enter distinct approver wallet addresses.'));
      return;
    }
    const amount = (value: string) => {
      const parsed = parseUnits(value, state.treasury.asset.decimals);
      if (!parsed.ok) {
        throw new Error(
          t('Enter a valid amount in {{asset}}.', {
            asset: state.treasury.asset.symbol,
          }),
        );
      }
      return parsed.value.toString();
    };
    try {
      const pay = {
        perRequest: amount(draft.payPerRequest),
        daily: amount(draft.payDaily),
      };
      const refill = {
        perRequest: amount(draft.refillPerRequest),
        daily: amount(draft.refillDaily),
      };
      const supply = {
        perRequest: amount(draft.supplyPerRequest),
        daily: amount(draft.supplyDaily),
      };
      if (
        BigInt(pay.perRequest) > BigInt(pay.daily) ||
        BigInt(refill.perRequest) > BigInt(refill.daily) ||
        BigInt(supply.perRequest) > BigInt(supply.daily)
      ) {
        throw new Error(t('A per-request limit cannot exceed its daily limit.'));
      }
      if ((BigInt(supply.perRequest) === 0n) !== (BigInt(supply.daily) === 0n)) {
        throw new Error(t('Set both supply limits to zero, or set both to a positive amount.'));
      }
      const buffers = treasuryWallets.map((safe) => {
        const values = draft.buffers[safe.role];
        if (!values) throw new Error(t('Add a buffer for every treasury Safe.'));
        const minimum = amount(values.minimum);
        const target = amount(values.target);
        if (safe.role !== 'T' && BigInt(target) < BigInt(minimum)) {
          throw new Error(
            t('An operational Safe target cannot be below its minimum.'),
          );
        }
        return { wallet: safe.safeAddress, minimum, target };
      });
      const whole = (value: string) =>
        /^\d+$/.test(value.trim()) ? Number(value) : NaN;
      const cooling = whole(draft.payeeCoolingSeconds);
      const approvalAgeDays = whole(draft.approvalMaxAgeDays);
      const expiresInDays = whole(draft.expiresInDays);
      if (
        !Number.isInteger(cooling) ||
        cooling < 1 ||
        cooling > 4_294_967_295 ||
        !Number.isInteger(approvalAgeDays) ||
        approvalAgeDays < 1 ||
        approvalAgeDays > 365 ||
        !Number.isInteger(expiresInDays) ||
        expiresInDays < 1 ||
        expiresInDays > 365
      ) {
        throw new Error(t('Enter valid cooling and mandate durations.'));
      }
      const validFrom = new Date();
      // A day of slack so signing delays do not eat into the chosen duration; the API caps a mandate at 365 days.
      const expiresAt = new Date(
        validFrom.getTime() + Math.min(expiresInDays + 1, 365) * 86_400_000,
      );
      const setup: ModuleSetupInput = {
        mandate: {
          validFrom: validFrom.toISOString(),
          expiresAt: expiresAt.toISOString(),
          payeeCoolingSeconds: cooling,
          executor: draft.executor.trim(),
          guardian: draft.guardian.trim(),
          pay,
          refill,
          supply,
          approvalMaxAge: approvalAgeDays * 86_400,
          approvers,
        },
        buffers,
      };
      await deploy.mutateAsync({
        treasuryId,
        setup,
      });
    } catch (error) {
      setFormError(
        error instanceof Error
          ? error.message
          : t('Could not prepare module transactions.'),
      );
    }
  };

  const update = (key: keyof ModuleDraft, value: string) =>
    setDraft((current) => ({ ...current, [key]: value }));
  return (
    <Card>
      <CardHeader
        title={t('Set up and enable the module')}
        description={t(
          'Set the initial limits and buffers. Treasury Safe and each operational Safe must approve its own transaction before coverage can be checked.',
        )}
      />
      <CardContent className="grid gap-4">
        {!GUARDIAN_VERIFICATION_AVAILABLE && (
          <Alert
            tone="warning"
            title={t('Guardian Safe verification is pending')}
          >
            {t(
              'The guardian address is included in the module settings, but this app cannot verify that it is a Safe controlled by the human guardian and pause-only Sentinel. You can enable the module now, but the Guardian Safe step stays blocked until that setup can be verified.',
            )}
          </Alert>
        )}
        {governance.isPending && <Skeleton className="h-20" />}
        {governance.isError && (
          <Alert tone="danger">{errorMessage(governance.error)}</Alert>
        )}
        {!governance.isPending && !hasPreparedTransactions && (
          <div className="grid gap-4">
            {hasPartialTransactions && (
              <Alert tone="warning">
                {t(
                  'Transactions were prepared for only some Safes. Prepare them again to cover every Safe.',
                )}
              </Alert>
            )}
            <Alert tone="neutral" title={t('Initial module settings')}>
              {t(
                'Amounts are entered in {{asset}} and sent to the API as integer base units. Use the executor address configured for this organization.',
                { asset: state.treasury.asset.symbol },
              )}
            </Alert>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field htmlFor="module-executor" label={t('Executor address')}>
                <Input
                  id="module-executor"
                  value={draft.executor}
                  onChange={(event) => update('executor', event.target.value)}
                />
              </Field>
              <Field
                htmlFor="module-guardian"
                label={t('Guardian address in module config')}
              >
                <Input
                  id="module-guardian"
                  value={draft.guardian}
                  onChange={(event) => update('guardian', event.target.value)}
                />
              </Field>
            </div>
            <Field
              htmlFor="module-approvers"
              label={t('Approver wallets')}
              hint={t('Enter distinct addresses, separated by spaces or commas.')}
            >
              <Textarea
                id="module-approvers"
                value={draft.approvers}
                onChange={(event) => update('approvers', event.target.value)}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-3">
              {([
                ['payeeCoolingSeconds', 'Payee cooling (seconds)'],
                ['approvalMaxAgeDays', 'Approval maximum age (days)'],
                ['expiresInDays', 'Mandate duration (days)'],
              ] as const).map(([key, label]) => (
                <Field key={key} htmlFor={`module-${key}`} label={t(label)}>
                  <Input
                    id={`module-${key}`}
                    inputMode="numeric"
                    value={draft[key]}
                    onChange={(event) => update(key, event.target.value)}
                  />
                </Field>
              ))}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {([
                ['PAY', 'payPerRequest', 'payDaily'],
                ['REFILL', 'refillPerRequest', 'refillDaily'],
                ['SUPPLY', 'supplyPerRequest', 'supplyDaily'],
              ] as const).map(([kind, perRequest, daily]) => (
                <fieldset
                  key={kind}
                  className="grid gap-3 rounded-md border border-border p-3"
                >
                  <legend className="px-1 text-sm font-medium">
                    {t('{{kind}} limits ({{asset}})', {
                      kind,
                      asset: state.treasury.asset.symbol,
                    })}
                  </legend>
                  <div className="grid grid-cols-2 gap-3">
                    <Field
                      htmlFor={`module-${kind.toLowerCase()}-request`}
                      label={t('Per request')}
                    >
                      <Input
                        id={`module-${kind.toLowerCase()}-request`}
                        inputMode="decimal"
                        value={draft[perRequest]}
                        onChange={(event) => update(perRequest, event.target.value)}
                      />
                    </Field>
                    <Field
                      htmlFor={`module-${kind.toLowerCase()}-daily`}
                      label={t('Per day')}
                    >
                      <Input
                        id={`module-${kind.toLowerCase()}-daily`}
                        inputMode="decimal"
                        value={draft[daily]}
                        onChange={(event) => update(daily, event.target.value)}
                      />
                    </Field>
                  </div>
                </fieldset>
              ))}
            </div>
            {treasuryWallets.map((safe) => (
              <fieldset
                key={safe.role}
                className="grid gap-3 rounded-md border border-border p-3"
              >
                <legend className="px-1 text-sm font-medium">
                  {t('{{label}} buffer', { label: safe.label })}
                </legend>
                <div className="grid grid-cols-2 gap-3">
                  {(['minimum', 'target'] as const).map((key) => (
                    <Field
                      key={key}
                      htmlFor={`buffer-${safe.role}-${key}`}
                      label={t('{{kind}} ({{asset}})', {
                        kind: key === 'minimum' ? 'Minimum' : 'Target',
                        asset: state.treasury.asset.symbol,
                      })}
                    >
                      <Input
                        id={`buffer-${safe.role}-${key}`}
                        inputMode="decimal"
                        value={draft.buffers[safe.role]?.[key] ?? ''}
                        onChange={(event) =>
                          setDraft((current) => ({
                            ...current,
                            buffers: {
                              ...current.buffers,
                              [safe.role]: {
                                ...current.buffers[safe.role],
                                [key]: event.target.value,
                              },
                            },
                          }))
                        }
                      />
                    </Field>
                  ))}
                </div>
              </fieldset>
            ))}
            {formError && <Alert tone="danger">{formError}</Alert>}
            {deploy.isError && (
              <Alert tone="danger">{errorMessage(deploy.error)}</Alert>
            )}
          </div>
        )}
        {txsBySafe.map((tx) =>
          tx ? <ModuleSetupTransaction key={tx.id} id={tx.id} /> : null,
        )}
      </CardContent>
      <CardFooter>
        {!hasPreparedTransactions ? (
          <Button
            variant="primary"
            loading={deploy.isPending}
            onClick={() => void prepare()}
          >
            {t('Prepare module transactions')}
          </Button>
        ) : (
          <Button variant="primary" disabled={!executed} onClick={onDone}>
            {t('Continue')}
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}

function ModuleSetupTransaction({ id }: { id: string }) {
  const scope = useOrgScope();
  const query = useGovernanceTx(scope.orgId, id);
  return (
    <QueryBoundary query={query}>
      {({ governanceTx, typedData }) => (
        <Card>
          <CardHeader
            title={governanceTx.title}
            description={governanceTx.summary}
          />
          <CardContent className="grid gap-4">
            <DecodedCalls calls={governanceTx.calls} />
            <GovernanceActions tx={governanceTx} typedData={typedData} />
          </CardContent>
        </Card>
      )}
    </QueryBoundary>
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
  const draftGuardian = readModuleDraft(state.treasury.id).guardian?.trim();
  const configuredAddress =
    draftGuardian && isAddress(draftGuardian)
      ? draftGuardian
      : state.wallets.find((wallet) => wallet.role === 'GUARDIAN')?.safeAddress;
  return (
    <Card>
      <CardHeader
        title={t('Guardian Safe')}
        description={t(
          'A Guardian Safe must have a human guardian and the pause-only Sentinel as owners. This step is pending until the app can create and verify that setup.',
        )}
      />
      <CardContent>
        <div className="grid gap-4">
          <Alert tone="warning" title={t('Guardian setup pending')}>
            {t(
              'This treasury cannot finish setup yet. A valid address by itself does not prove that it is a Guardian Safe or that the Sentinel can pause through it.',
            )}
          </Alert>
          {configuredAddress && (
            <Field
              htmlFor="guardian-configured-address"
              label={t('Address included in module settings (unverified)')}
            >
              <Input
                id="guardian-configured-address"
                className="num"
                value={configuredAddress}
                readOnly
                aria-describedby="guardian-setup-dependency"
              />
            </Field>
          )}
          <p
            id="guardian-setup-dependency"
            className="text-sm text-muted-foreground"
          >
            {t(
              'Guardian Safe deployment, registration and Sentinel health checks depend on MDT-010 and its signer and module setup prerequisites.',
            )}
          </p>
        </div>
      </CardContent>
      <CardFooter>
        <Button
          variant="primary"
          disabled={!GUARDIAN_VERIFICATION_AVAILABLE}
          aria-describedby="guardian-setup-dependency"
        >
          {t('Finish setup — Guardian verification required')}
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
  guardianPending?: boolean;
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
              value: data.guardianPending ? (
                <span>{t('Verification pending')}</span>
              ) : data.guardian ? (
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
  const query = useTreasurySetup(scope.orgId, treasuryId);
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
          asset: assetLabel(state.treasury.asset),
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
          // An address alone does not prove Sentinel ownership or health: only a
          // GUARDIAN wallet on an Active treasury counts as verified.
          guardian: guardian?.safeAddress,
          guardianPending: !guardian || state.treasury.status !== 'Active',
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
