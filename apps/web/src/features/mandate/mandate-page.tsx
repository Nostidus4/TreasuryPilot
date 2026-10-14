import { Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Amount, AmountInput } from '@/components/domain/amount';
import { Address } from '@/components/domain/chain';
import { DiffView, KeyValueList } from '@/components/domain/display';
import { StatusBadge } from '@/components/domain/status';
import { QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from '@/components/ui/card';
import { Field, Input } from '@/components/ui/input';
import { Alert } from '@/components/ui/misc';
import {
  useMandateActivationTx,
  useMandates,
  useSaveMandateDraft,
} from '@/features/controls/api';
import { useMembers } from '@/features/orgs/api';
import { useTreasuryScope } from '@/features/orgs/org-scope';
import { useTreasury } from '@/features/treasury/api';
import { useChain, useChains } from '@/lib/api/chains';
import { errorMessage, isApiError } from '@/lib/api/http';
import type {
  Asset,
  Hex,
  MandateConfig,
  MandateDraft,
  MandateVersion,
  TreasuryState,
} from '@/lib/api/types';
import { formatDate, formatDateTime } from '@/lib/format';
import { t } from '@/lib/i18n';
import { formatUnits, parseUnits } from '@/lib/money';
import { mandateStatus } from '@/lib/status';

type Amounts = Record<string, string>;

const amountFields = (
  config: MandateConfig,
  assetDecimals: Map<string, number>,
  primaryDecimals: number,
) => [
  { key: 'limits.PAY.perRequest', value: config.limits.PAY.perRequest, decimals: primaryDecimals },
  { key: 'limits.PAY.daily', value: config.limits.PAY.daily, decimals: primaryDecimals },
  { key: 'limits.REFILL.perRequest', value: config.limits.REFILL.perRequest, decimals: primaryDecimals },
  { key: 'limits.REFILL.daily', value: config.limits.REFILL.daily, decimals: primaryDecimals },
  ...config.buffers.flatMap((buffer) => [
    { key: `buffers.${buffer.wallet}.minimum`, value: buffer.minimum, decimals: primaryDecimals },
    { key: `buffers.${buffer.wallet}.target`, value: buffer.target, decimals: primaryDecimals },
  ]),
  ...(config.assetPolicies ?? []).flatMap((policy) => {
    const decimals = assetDecimals.get(policy.assetId);
    if (decimals === undefined) return [];
    return [
      ...(['PAY', 'REFILL'] as const).flatMap((action) => [
        { key: `assetPolicies.${policy.assetId}.limits.${action}.perRequest`, value: policy.limits[action].perRequest, decimals },
        { key: `assetPolicies.${policy.assetId}.limits.${action}.daily`, value: policy.limits[action].daily, decimals },
      ]),
      ...policy.buffers.flatMap((buffer) => [
        { key: `assetPolicies.${policy.assetId}.buffers.${buffer.wallet}.minimum`, value: buffer.minimum, decimals },
        ...(buffer.target === undefined
          ? []
          : [{ key: `assetPolicies.${policy.assetId}.buffers.${buffer.wallet}.target`, value: buffer.target, decimals }]),
      ]),
    ];
  }),
];

function blankConfig(state: TreasuryState): MandateConfig {
  const zero = { perRequest: '0', daily: '0' };
  const expires = new Date(Date.now() + 30 * 86_400_000).toISOString();
  return {
    actions: ['REFILL', 'PAY'],
    assetPolicies: [],
    limits: { PAY: zero, REFILL: zero },
    buffers: state.wallets
      .filter((wallet) => wallet.role === 'O1' || wallet.role === 'O2')
      .map((wallet) => ({ wallet: wallet.role, minimum: '0', target: '0' })),
    executor: state.treasury.moduleAddress,
    approvers: [],
    guardian:
      state.wallets.find((wallet) => wallet.role === 'GUARDIAN')?.safeAddress ??
      state.treasury.moduleAddress,
    validFrom: new Date().toISOString(),
    expiresAt: expires,
  };
}

function Summary({ version }: { version: MandateVersion }) {
  const { config } = version;
  return (
    <KeyValueList
      items={[
        {
          label: t('Payments'),
          hint: t('per request / per UTC day'),
          value: (
            <span className="grid justify-items-end">
              <Amount value={config.limits.PAY.perRequest} context="column" />
              <Amount value={config.limits.PAY.daily} context="column" muted />
            </span>
          ),
        },
        {
          label: t('Refills'),
          hint: t('per request / per UTC day'),
          value: (
            <span className="grid justify-items-end">
              <Amount
                value={config.limits.REFILL.perRequest}
                context="column"
              />
              <Amount
                value={config.limits.REFILL.daily}
                context="column"
                muted
              />
            </span>
          ),
        },
        ...config.buffers.map((buffer) => ({
          label: t('Safe {{role}}', { role: buffer.wallet }),
          hint: t('minimum buffer / target'),
          value: (
            <span className="grid justify-items-end">
              <Amount value={buffer.minimum} context="column" />
              <Amount value={buffer.target} context="column" muted />
            </span>
          ),
        })),
        {
          label: t('Approvers'),
          value: (
            <span className="grid justify-items-end gap-0.5">
              {config.approvers.map((approver) => (
                <Address key={approver} address={approver} />
              ))}
            </span>
          ),
        },
        { label: t('Executor'), value: <Address address={config.executor} /> },
        { label: t('Guardian'), value: <Address address={config.guardian} /> },
        { label: t('Expires'), value: formatDate(config.expiresAt) },
      ]}
    />
  );
}

/**
 * Mandate editor (WEB-005). The form produces a draft; the server returns a
 * plain-language summary and a looser/stricter diff; activation is a
 * governance transaction signed by the Safe owners.
 */
function Editor({
  base,
  state,
  versions,
}: {
  base: MandateConfig;
  state: TreasuryState;
  versions: MandateVersion[];
}) {
  const scope = useTreasuryScope();
  const navigate = useNavigate();
  const decimals = state.treasury.asset.decimals;
  const chain = useChain(state.treasury.chainId);
  const availableAssets = (chain?.assets ?? []).filter(
    (asset) => asset.id !== state.treasury.asset.id,
  );
  const decimalsByAsset = new Map(
    availableAssets.map((asset) => [asset.id, asset.decimals]),
  );
  const members = useMembers(scope.orgId);
  const saveDraft = useSaveMandateDraft(scope.orgId, scope.treasuryId);
  const activation = useMandateActivationTx(scope.orgId, scope.treasuryId);

  const [amounts, setAmounts] = useState<Amounts>(() =>
    Object.fromEntries(
      amountFields(base, decimalsByAsset, decimals).map((field) => [
        field.key,
        formatUnits(field.value, field.decimals, { group: false }),
      ]),
    ),
  );
  const [enabledAssets, setEnabledAssets] = useState<string[]>(
    (base.assetPolicies ?? []).map((policy) => policy.assetId),
  );
  // Wallets are read at build time so a refreshed treasury state is never missed.
  const policyWallets = state.wallets.filter(
    (wallet) => wallet.role === 'T' || wallet.role === 'O1' || wallet.role === 'O2',
  );
  const [approvers, setApprovers] = useState<Hex[]>(base.approvers);
  const [newApprover, setNewApprover] = useState('');
  const [expiresAt, setExpiresAt] = useState(base.expiresAt.slice(0, 10));
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<MandateDraft>();

  const serverErrors = isApiError(saveDraft.error)
    ? Object.fromEntries(
        (saveDraft.error.problem.errors ?? []).map((item) => [
          item.field,
          item.message,
        ]),
      )
    : {};
  const errorFor = (key: string) => localErrors[key] ?? serverErrors[key];
  const touch = () => setPreview(undefined);

  const build = (): MandateConfig | null => {
    const errors: Record<string, string> = {};
    const readAmount = (key: string, precision: number) => {
      const parsed = parseUnits(amounts[key] ?? '', precision);
      if (!parsed.ok) {
        errors[key] =
          parsed.error === 'TOO_PRECISE'
            ? t('At most {{count}} decimal places.', { count: precision })
            : t('Enter an amount.');
        return '0';
      }
      return parsed.value.toString();
    };
    const read = (key: string) => readAmount(key, decimals);
    const config: MandateConfig = {
      ...base,
      limits: {
        PAY: {
          perRequest: read('limits.PAY.perRequest'),
          daily: read('limits.PAY.daily'),
        },
        REFILL: {
          perRequest: read('limits.REFILL.perRequest'),
          daily: read('limits.REFILL.daily'),
        },
      },
      buffers: base.buffers.map((buffer) => ({
        wallet: buffer.wallet,
        minimum: read(`buffers.${buffer.wallet}.minimum`),
        target: read(`buffers.${buffer.wallet}.target`),
      })),
      assetPolicies: enabledAssets.map((assetId) => {
        const precision = decimalsByAsset.get(assetId);
        const read = (key: string) => {
          if (precision !== undefined) return readAmount(key, precision);
          errors[key] = t('Asset decimals are unavailable.');
          return '0';
        };
        return {
          assetId,
          limits: {
            PAY: {
              perRequest: read(`assetPolicies.${assetId}.limits.PAY.perRequest`),
              daily: read(`assetPolicies.${assetId}.limits.PAY.daily`),
            },
            REFILL: {
              perRequest: read(`assetPolicies.${assetId}.limits.REFILL.perRequest`),
              daily: read(`assetPolicies.${assetId}.limits.REFILL.daily`),
            },
          },
          buffers: policyWallets.map((wallet) => ({
            wallet: wallet.safeAddress,
            minimum: read(`assetPolicies.${assetId}.buffers.${wallet.safeAddress}.minimum`),
            // Safe T has no refill target.
            ...(wallet.role === 'T'
              ? {}
              : { target: read(`assetPolicies.${assetId}.buffers.${wallet.safeAddress}.target`) }),
          })),
        };
      }),
      approvers,
      expiresAt: `${expiresAt}T00:00:00.000Z`,
    };
    if (!expiresAt || config.expiresAt <= new Date().toISOString()) {
      errors.expiresAt = t('Choose a date in the future.');
    }
    setLocalErrors(errors);
    return Object.keys(errors).length === 0 ? config : null;
  };

  const toggleAssetPolicy = (assetId: string, enabled: boolean) => {
    touch();
    const prefix = `assetPolicies.${assetId}.`;
    const without = <T,>(record: Record<string, T>) =>
      Object.fromEntries(Object.entries(record).filter(([key]) => !key.startsWith(prefix)));
    setLocalErrors(without);
    if (enabled) {
      const keys = [
        ...(['PAY', 'REFILL'] as const).flatMap((action) => [
          `${prefix}limits.${action}.perRequest`,
          `${prefix}limits.${action}.daily`,
        ]),
        ...policyWallets.flatMap((wallet) => [
          `${prefix}buffers.${wallet.safeAddress}.minimum`,
          ...(wallet.role === 'T' ? [] : [`${prefix}buffers.${wallet.safeAddress}.target`]),
        ]),
      ];
      setEnabledAssets((current) => [...current, assetId]);
      setAmounts((current) => ({ ...current, ...Object.fromEntries(keys.map((key) => [key, '0'])) }));
    } else {
      setEnabledAssets((current) => current.filter((id) => id !== assetId));
      setAmounts(without);
    }
  };

  const amountField = (key: string, label: string, hint?: string, asset?: Asset) => (
    <Field htmlFor={key} label={label} error={errorFor(key)} hint={hint}>
      <AmountInput
        asset={asset}
        id={key}
        value={amounts[key] ?? ''}
        aria-invalid={Boolean(errorFor(key))}
        onChange={(event) => {
          touch();
          setAmounts((current) => ({ ...current, [key]: event.target.value }));
        }}
      />
    </Field>
  );

  const addApprover = (address: string) => {
    if (!/^0x[0-9a-fA-F]{40}$/.test(address)) {
      setLocalErrors((current) => ({
        ...current,
        approvers: t('Enter a 0x address with 40 hex characters.'),
      }));
      return;
    }
    touch();
    setLocalErrors(({ approvers: _removed, ...rest }) => rest);
    if (
      !approvers.some((item) => item.toLowerCase() === address.toLowerCase())
    ) {
      setApprovers((current) => [...current, address as Hex]);
    }
    setNewApprover('');
  };

  const memberName = (address: string) =>
    members.data?.items.find(
      (member) => member.wallet?.toLowerCase() === address.toLowerCase(),
    )?.name;
  const suggestions =
    members.data?.items.filter(
      (member) =>
        member.wallet &&
        member.roles.includes('APR') &&
        !approvers.some(
          (item) => item.toLowerCase() === member.wallet!.toLowerCase(),
        ),
    ) ?? [];
  const pending = versions.find((item) => item.status === 'PendingActivation');

  return (
    <div className="grid items-start gap-4 lg:grid-cols-5">
      <form
        className="grid gap-4 lg:col-span-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const config = build();
          if (config) saveDraft.mutate(config, { onSuccess: setPreview });
        }}
      >
        <Card>
          <CardHeader
            title={t('Payment limits')}
            description={t(
              'The contract rejects any payment above these, whoever asks.',
            )}
          />
          <CardContent className="grid gap-4 sm:grid-cols-2">
            {amountField(
              'limits.PAY.perRequest',
              t('Per request'),
              t('Larger invoices need a one-time exception.'),
            )}
            {amountField('limits.PAY.daily', t('Per UTC day'))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader
            title={t('Refill limits')}
            description={t(
              'Moves from the Treasury Safe to an operational Safe.',
            )}
          />
          <CardContent className="grid gap-4 sm:grid-cols-2">
            {amountField('limits.REFILL.perRequest', t('Per request'))}
            {amountField('limits.REFILL.daily', t('Per UTC day'))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader
            title={t('Additional payment assets')}
            description={t('Enable configured assets on this treasury and set independent PAY, REFILL, and wallet buffer limits.')}
          />
          <CardContent className="grid gap-5">
            {availableAssets.map((asset) => {
              const enabled = enabledAssets.includes(asset.id);
              return (
                <section key={asset.id} className="grid gap-3 rounded-lg border p-3">
                  <label className="flex items-center gap-2 font-medium">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(event) => toggleAssetPolicy(asset.id, event.target.checked)}
                    />
                    {asset.isTest ? `${asset.symbol} (${t('test asset')})` : asset.symbol}
                  </label>
                  {enabled && (
                    <div className="grid gap-4">
                      <div className="grid gap-4 sm:grid-cols-2">
                        {(['PAY', 'REFILL'] as const).flatMap((action) => [
                          amountField(`assetPolicies.${asset.id}.limits.${action}.perRequest`, `${action} · ${t('Per request')}`, undefined, asset),
                          amountField(`assetPolicies.${asset.id}.limits.${action}.daily`, `${action} · ${t('Per UTC day')}`, undefined, asset),
                        ])}
                      </div>
                      {policyWallets.map((wallet) => (
                        <fieldset key={wallet.safeAddress} className="grid gap-3 sm:grid-cols-2">
                          <legend className="text-sm font-medium">{wallet.label}</legend>
                          {amountField(`assetPolicies.${asset.id}.buffers.${wallet.safeAddress}.minimum`, t('Minimum buffer'), undefined, asset)}
                          {wallet.role !== 'T' &&
                            amountField(`assetPolicies.${asset.id}.buffers.${wallet.safeAddress}.target`, t('Target balance'), undefined, asset)}
                        </fieldset>
                      ))}
                    </div>
                  )}
                </section>
              );
            })}
            {availableAssets.length === 0 && (
              <p className="text-sm text-muted-foreground">{t('No additional assets are configured on this chain.')}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader
            title={t('Buffers')}
            description={t(
              'A payment that would take a Safe below its minimum is rejected. Refills aim for the target.',
            )}
          />
          <CardContent className="grid gap-5">
            {base.buffers.length === 0 && (
              <p className="text-sm text-muted-foreground">
                {t('This treasury has no operational Safe to protect.')}
              </p>
            )}
            {base.buffers.map((buffer) => (
              <fieldset
                key={buffer.wallet}
                className="grid gap-4 sm:grid-cols-2"
              >
                <legend className="mb-2 text-sm font-medium">
                  {state.wallets.find((wallet) => wallet.role === buffer.wallet)
                    ?.label ?? buffer.wallet}{' '}
                  <span className="font-normal text-muted-foreground">
                    ({buffer.wallet})
                  </span>
                </legend>
                {amountField(
                  `buffers.${buffer.wallet}.minimum`,
                  t('Minimum buffer'),
                )}
                {amountField(
                  `buffers.${buffer.wallet}.target`,
                  t('Target balance'),
                )}
              </fieldset>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader
            title={t('Approvers')}
            description={t(
              'Only signatures from these wallets approve a payment.',
            )}
          />
          <CardContent className="grid gap-3">
            {approvers.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t('No approver wallets yet. Add at least one.')}
              </p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {approvers.map((approver) => (
                  <li
                    key={approver}
                    className="flex items-center gap-2 px-3 py-2"
                  >
                    <Address address={approver} label={memberName(approver)} />
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="ml-auto"
                      aria-label={t('Remove approver {{address}}', {
                        address: approver,
                      })}
                      onClick={() => {
                        touch();
                        setApprovers((current) =>
                          current.filter((item) => item !== approver),
                        );
                      }}
                    >
                      <Trash2 aria-hidden="true" />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            {suggestions.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-muted-foreground">
                  {t('Members with the Approver role:')}
                </span>
                {suggestions.map((member) => (
                  <Button
                    key={member.userId}
                    size="sm"
                    onClick={() => addApprover(member.wallet!)}
                  >
                    <Plus aria-hidden="true" />
                    {member.name}
                  </Button>
                ))}
              </div>
            )}
            <Field
              htmlFor="new-approver"
              label={t('Add a wallet address')}
              error={errorFor('approvers')}
            >
              <div className="flex gap-2">
                <Input
                  id="new-approver"
                  className="num"
                  placeholder="0x…"
                  value={newApprover}
                  aria-invalid={Boolean(errorFor('approvers'))}
                  onChange={(event) =>
                    setNewApprover(event.target.value.trim())
                  }
                />
                <Button onClick={() => addApprover(newApprover)}>
                  {t('Add')}
                </Button>
              </div>
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader
            title={t('Expiry')}
            description={t(
              'After this date the module stops executing until a new mandate is activated.',
            )}
          />
          <CardContent>
            <Field
              htmlFor="expiresAt"
              label={t('Expires on')}
              error={errorFor('expiresAt')}
            >
              <Input
                id="expiresAt"
                type="date"
                className="sm:w-56"
                value={expiresAt}
                aria-invalid={Boolean(errorFor('expiresAt'))}
                onChange={(event) => {
                  touch();
                  setExpiresAt(event.target.value);
                }}
              />
            </Field>
          </CardContent>
          <CardFooter>
            {saveDraft.isError && Object.keys(serverErrors).length === 0 && (
              <p
                role="alert"
                className="mr-auto text-sm text-danger-foreground"
              >
                {errorMessage(saveDraft.error)}
              </p>
            )}
            <Button
              type="submit"
              variant="primary"
              loading={saveDraft.isPending}
            >
              {t('Save draft and preview')}
            </Button>
          </CardFooter>
        </Card>
      </form>

      <aside className="grid gap-4 lg:sticky lg:top-[4.5rem] lg:col-span-2">
        {pending && (
          <Alert
            tone="warning"
            title={t('v{{version}} is waiting for signatures', {
              version: pending.version,
            })}
          >
            {t('A new draft will supersede it once activated.')}
          </Alert>
        )}
        <Card>
          <CardHeader
            title={
              preview
                ? t('Draft v{{version}}', { version: preview.draft.version })
                : t('Preview')
            }
            description={
              preview
                ? t('What this mandate allows, in plain language.')
                : t(
                    'Save the draft to see what it allows and how it differs from the active mandate.',
                  )
            }
          />
          {preview && (
            <>
              <CardContent className="grid gap-4">
                <ul className="list-disc space-y-1.5 pl-5 text-base">
                  {preview.summary.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                <div>
                  <h3 className="mb-2 text-sm font-medium">
                    {t('Changes against the active mandate')}
                  </h3>
                  <DiffView
                    diff={preview.diff}
                    emptyText={
                      versions.some((item) => item.status === 'Active')
                        ? undefined
                        : t('This is the first mandate for this treasury.')
                    }
                  />
                </div>
                {preview.diff.some((entry) => entry.direction === 'LOOSER') && (
                  <Alert tone="warning">
                    {t(
                      'This draft loosens at least one control. Owners will see the same comparison before they sign.',
                    )}
                  </Alert>
                )}
                {activation.isError && (
                  <Alert tone="danger">{errorMessage(activation.error)}</Alert>
                )}
              </CardContent>
              <CardFooter>
                <Button
                  variant="primary"
                  loading={activation.isPending}
                  onClick={() =>
                    activation.mutate(preview.draft.version, {
                      onSuccess: ({ governanceTx }) =>
                        navigate(`${scope.base}/governance/${governanceTx.id}`),
                    })
                  }
                >
                  {t('Create governance transaction')}
                </Button>
              </CardFooter>
            </>
          )}
        </Card>
      </aside>
    </div>
  );
}

export function MandatePage() {
  const scope = useTreasuryScope();
  const mandates = useMandates(scope.orgId, scope.treasuryId);
  const treasury = useTreasury(scope.orgId, scope.treasuryId);
  const chains = useChains();
  const canEdit = scope.can('OWN');
  const active = mandates.data?.items.find((item) => item.status === 'Active');

  return (
    <Page
      width="wide"
      title={t('Mandate')}
      titleSlot={active && <StatusBadge meta={mandateStatus(active.status)} />}
      description={t(
        'The mandate is the standing permission you give the agent: what it may do, up to which amounts, with whose approval. It lives in the contract, so it holds even if the backend is compromised.',
      )}
    >
      <QueryBoundary query={mandates}>
        {({ items }) => (
          <QueryBoundary query={treasury}>
            {(state) => (
              <div className="grid gap-6">
                {!canEdit && (
                  <Alert tone="neutral" title={t('View only')}>
                    {t('Only Safe owners can change the mandate.')}
                  </Alert>
                )}
                {canEdit ? (
                  // Secondary-asset decimals come from the chain query; wait for it.
                  <QueryBoundary query={chains}>
                    {() => (
                      <Editor
                        key={active?.version ?? 'new'}
                        base={active?.config ?? blankConfig(state)}
                        state={state}
                        versions={items}
                      />
                    )}
                  </QueryBoundary>
                ) : active ? (
                  <Card className="max-w-2xl">
                    <CardHeader
                      title={t('Active mandate v{{version}}', {
                        version: active.version,
                      })}
                    />
                    <CardContent>
                      <Summary version={active} />
                    </CardContent>
                  </Card>
                ) : (
                  <Alert tone="warning">{t('No mandate is active yet.')}</Alert>
                )}

                <Card>
                  <CardHeader title={t('Version history')} />
                  {items.length === 0 ? (
                    <CardContent className="text-sm text-muted-foreground">
                      {t(
                        'No versions yet. The first activated mandate appears here.',
                      )}
                    </CardContent>
                  ) : (
                    <ul className="divide-y">
                      {items.map((version) => (
                        <li key={version.version}>
                          <details>
                            <summary className="flex cursor-pointer flex-wrap items-center gap-3 px-4 py-3 hover:bg-surface-muted">
                              <span className="num text-base font-medium">
                                v{version.version}
                              </span>
                              <StatusBadge
                                meta={mandateStatus(version.status)}
                              />
                              <span className="ml-auto text-sm text-muted-foreground">
                                {version.activatedAt
                                  ? t('Activated {{date}}', {
                                      date: formatDateTime(version.activatedAt),
                                    })
                                  : t('Created {{date}}', {
                                      date: formatDateTime(version.createdAt),
                                    })}
                              </span>
                            </summary>
                            <div className="max-w-2xl px-4 pb-4">
                              <Summary version={version} />
                            </div>
                          </details>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
            )}
          </QueryBoundary>
        )}
      </QueryBoundary>
    </Page>
  );
}
