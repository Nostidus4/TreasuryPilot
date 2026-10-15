import { format } from 'date-fns';
import { ChevronRight, CircleAlert, TriangleAlert } from 'lucide-react';
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useNavigate } from 'react-router-dom';

import { t } from '@/lib/i18n';
import { formatUnits } from '@/lib/money';
import { cn } from '@/lib/utils';
import type {
  Budget,
  Forecast,
  PaymentRequest,
  Position,
  TreasuryWallet,
} from '@/lib/api/types';

/*
 * Linked overview charts. Every chart reads and writes one shared focus:
 * the Safe (or Aave) being looked at, the purpose of the money inside it,
 * and the day on the runway. Hovering anything highlights the same thing in
 * every other chart, so the page reads as one picture rather than four.
 *
 * Geometry uses display-unit numbers; every value shown as text uses the
 * exact bigint formatting from lib/money.
 */

export type Place = 'T' | 'AAVE' | 'O1' | 'O2';
export type Purpose =
  | 'reserve'
  | 'floor'
  | 'holds'
  | 'free'
  | 'withdrawable'
  | 'illiquid'
  | 'buffer'
  | 'spendable';

interface Focus {
  place?: Place;
  purpose?: Purpose;
  day?: number;
}

interface FocusContextValue {
  focus: Focus;
  setFocus: (next: Focus) => void;
  /** A pinned location: zoomed in the icicle, highlighted everywhere else. */
  selected?: Place;
  setSelected: (next: Place | undefined) => void;
}

const FocusContext = createContext<FocusContextValue>({
  focus: {},
  setFocus: () => undefined,
  setSelected: () => undefined,
});

export function OverviewFocusProvider({ children }: { children: ReactNode }) {
  const [focus, setFocus] = useState<Focus>({});
  const [selected, setSelected] = useState<Place>();
  const value = useMemo(
    () => ({ focus, setFocus, selected, setSelected }),
    [focus, selected],
  );
  return (
    <FocusContext.Provider value={value}>{children}</FocusContext.Provider>
  );
}

function useFocus() {
  const context = useContext(FocusContext);
  // Hover wins; otherwise the pinned location stays highlighted.
  const place = context.focus.place ?? context.selected;
  return { ...context, place };
}

/* ------------------------------------------------------------------ */
/* Shared helpers                                                      */
/* ------------------------------------------------------------------ */

const placeColor: Record<Place, string> = {
  T: 'var(--chart-1)',
  AAVE: 'var(--chart-2)',
  O1: 'var(--chart-3)',
  O2: 'var(--chart-4)',
};

/** Money that is held back (reserves, buffers) is hatched; usable money is solid. */
const heldPurposes = new Set<Purpose>([
  'reserve',
  'floor',
  'holds',
  'illiquid',
  'buffer',
]);

export interface Units {
  decimals: number;
  symbol: string;
}

function toNumber(value: string | bigint, units: Units) {
  return Number(formatUnits(value, units.decimals, { group: false }));
}

function money(value: string | bigint, units: Units) {
  return `${formatUnits(value, units.decimals)} ${units.symbol}`;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.floor(entry.contentRect.width)),
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/** One diagonal hatch per colour, so held-back money reads as "locked". */
function HatchDefs({ ids }: { ids: Array<[string, string]> }) {
  return (
    <defs>
      {ids.map(([id, color]) => (
        <pattern
          key={id}
          id={id}
          width="6"
          height="6"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <rect width="6" height="6" fill={color} opacity="0.35" />
          <line x1="0" y1="0" x2="0" y2="6" stroke={color} strokeWidth="2.5" />
        </pattern>
      ))}
    </defs>
  );
}

interface TipState {
  x: number;
  y: number;
  value: string;
  label: string;
  detail?: string;
}

function Tip({ tip }: { tip: TipState | null }) {
  if (!tip) return null;
  return (
    <div
      role="status"
      className="pointer-events-none absolute z-10 w-max max-w-64 -translate-x-1/2 -translate-y-full rounded-md border bg-surface px-2.5 py-1.5 shadow-float"
      style={{ left: tip.x, top: tip.y - 8 }}
    >
      <p className="num text-sm font-semibold text-foreground">{tip.value}</p>
      <p className="text-xs text-muted-foreground">{tip.label}</p>
      {tip.detail && (
        <p className="mt-0.5 text-xs text-subtle-foreground">{tip.detail}</p>
      )}
    </div>
  );
}

function Swatch({
  color,
  hatched,
  dashed,
}: {
  color: string;
  hatched?: boolean;
  dashed?: boolean;
}) {
  return (
    <span
      aria-hidden="true"
      className="inline-block size-2.5 shrink-0 rounded-sm"
      style={{
        background: dashed
          ? 'transparent'
          : hatched
            ? `repeating-linear-gradient(45deg, ${color} 0 2px, transparent 2px 4px)`
            : color,
        boxShadow: hatched ? `inset 0 0 0 1px ${color}` : undefined,
        border: dashed ? `1px dashed ${color}` : undefined,
      }}
    />
  );
}

function TableToggle({ children }: { children: ReactNode }) {
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
        {t('View as table')}
      </summary>
      <div className="mt-2 overflow-x-auto">{children}</div>
    </details>
  );
}

/* ------------------------------------------------------------------ */
/* 1. Liquidity icicle: where the money is, and what it is for         */
/* ------------------------------------------------------------------ */

interface Leaf {
  purpose: Purpose;
  label: string;
  value: bigint;
}

interface Branch {
  place: Place;
  label: string;
  value: bigint;
  children: Leaf[];
}

const min = (a: bigint, b: bigint) => (a < b ? a : b);
const pos = (value: bigint) => (value > 0n ? value : 0n);

// eslint-disable-next-line react-refresh/only-export-components
export function buildBranches(
  position: Position,
  wallets: TreasuryWallet[],
): Branch[] {
  const big = (value: string) => BigInt(value);
  const treasury = big(position.safeUsdc);
  const reserve = position.requiredReserve;
  const aave = big(position.aUsdc);
  const withdrawable = min(aave, big(position.poolLiquidity));
  const branches: Branch[] = [
    {
      place: 'T',
      label: t('Treasury Safe'),
      value: treasury,
      children: [
        {
          purpose: 'reserve' as const,
          label: t('Payment reserve'),
          value: big(reserve.paymentReserve),
        },
        {
          purpose: 'floor' as const,
          label: t('Floor'),
          value: big(reserve.floor),
        },
        {
          purpose: 'holds' as const,
          label: t('Holds'),
          value: big(reserve.holds),
        },
        {
          purpose: 'free' as const,
          label: t('Free to supply'),
          value: pos(treasury - big(reserve.total)),
        },
      ].filter((leaf) => leaf.value > 0n),
    },
    {
      place: 'AAVE',
      label: t('Aave V3'),
      value: aave,
      children: [
        {
          purpose: 'withdrawable' as const,
          label: t('Withdrawable now'),
          value: withdrawable,
        },
        {
          purpose: 'illiquid' as const,
          label: t('Waiting on pool liquidity'),
          value: aave - withdrawable,
        },
      ].filter((leaf) => leaf.value > 0n),
    },
  ];
  for (const role of ['O1', 'O2'] as const) {
    const wallet = wallets.find((item) => item.role === role);
    if (!wallet) continue;
    const balance = big(wallet.balance);
    const buffer = min(balance, big(wallet.buffer));
    branches.push({
      place: role,
      label: wallet.label,
      value: balance,
      children: [
        {
          purpose: 'buffer' as const,
          label: t('Minimum buffer'),
          value: buffer,
        },
        {
          purpose: 'spendable' as const,
          label: t('Spendable'),
          value: balance - buffer,
        },
      ].filter((leaf) => leaf.value > 0n),
    });
  }
  return branches.filter((branch) => branch.value > 0n);
}

/** Lay out values on [0, width] with a 2px gap and a minimum visible width. */
function layout<T>(items: T[], value: (item: T) => number, width: number) {
  const gap = 2;
  const minWidth = 6;
  const total = items.reduce((sum, item) => sum + value(item), 0) || 1;
  const usable = Math.max(0, width - gap * (items.length - 1));
  const raw = items.map((item) => (value(item) / total) * usable);
  const boosted = raw.map((w) => Math.max(w, minWidth));
  const extra = boosted.reduce((s, w) => s + w, 0) - usable;
  const shrinkable = raw.reduce((s, w) => s + (w > minWidth ? w : 0), 0) || 1;
  const widths = boosted.map((w, i) =>
    raw[i] > minWidth ? w - (extra * raw[i]) / shrinkable : w,
  );
  let x = 0;
  return items.map((item, index) => {
    const box = { item, x, width: widths[index] };
    x += widths[index] + gap;
    return box;
  });
}

export function LiquidityIcicle({
  branches,
  units,
}: {
  branches: Branch[];
  units: Units;
}) {
  const {
    focus,
    place,
    setFocus,
    selected: zoom,
    setSelected: setZoom,
  } = useFocus();
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState | null>(null);

  const visible = zoom
    ? branches.filter((branch) => branch.place === zoom)
    : branches;
  const total = branches.reduce((sum, branch) => sum + branch.value, 0n);
  const n = (value: bigint) => toNumber(value, units);
  const share = (value: bigint) =>
    total === 0n ? '0%' : `${((n(value) / n(total)) * 100).toFixed(1)}%`;

  const top = layout(visible, (branch) => n(branch.value), width);
  const rowTop = 44;
  const rowLeaf = 36;
  const height = rowTop + 2 + rowLeaf;
  const dim = (item: Place, purpose?: Purpose) =>
    (place && place !== item) ||
    (focus.purpose && purpose && focus.purpose !== purpose)
      ? 0.3
      : 1;

  const show = (
    content: Omit<TipState, 'x' | 'y'>,
    box: { x: number; y: number; width: number },
  ) => setTip({ ...content, x: box.x + box.width / 2, y: box.y });

  return (
    <div className="grid gap-3">
      <nav
        aria-label={t('Liquidity level')}
        className="flex items-center gap-1 text-sm"
      >
        <button
          type="button"
          className={cn(
            'rounded-sm px-1 hover:text-foreground',
            zoom
              ? 'text-muted-foreground underline-offset-4 hover:underline'
              : 'font-medium text-foreground',
          )}
          onClick={() => setZoom(undefined)}
        >
          {t('All funds')}
        </button>
        {zoom && (
          <>
            <ChevronRight
              className="size-3.5 text-subtle-foreground"
              aria-hidden="true"
            />
            <span className="font-medium">
              {branches.find((branch) => branch.place === zoom)?.label}
            </span>
          </>
        )}
        <span className="ml-auto text-xs text-subtle-foreground">
          {zoom
            ? t('Click again to zoom out')
            : t('Click a location to zoom in')}
        </span>
      </nav>

      <div
        ref={ref}
        className="relative"
        onPointerLeave={() => {
          setTip(null);
          setFocus({ ...focus, place: undefined, purpose: undefined });
        }}
      >
        {width > 0 && (
          <svg
            width={width}
            height={height}
            role="img"
            aria-label={t(
              'Icicle chart: total funds split by location, each location split by what the money is held for.',
            )}
            className="block overflow-visible"
          >
            <HatchDefs
              ids={visible.map((branch) => [
                `hatch-${branch.place}`,
                placeColor[branch.place],
              ])}
            />
            {top.map(({ item: branch, x, width: w }) => {
              const leaves = layout(
                branch.children,
                (leaf) => n(leaf.value),
                w,
              );
              return (
                <g key={branch.place}>
                  <g
                    tabIndex={0}
                    role="button"
                    aria-label={`${branch.label}: ${money(branch.value, units)}`}
                    className="cursor-pointer outline-none"
                    opacity={dim(branch.place)}
                    onPointerEnter={() => {
                      setFocus({
                        ...focus,
                        place: branch.place,
                        purpose: undefined,
                      });
                      show(
                        {
                          value: money(branch.value, units),
                          label: branch.label,
                          detail: t('{{share}} of all funds', {
                            share: share(branch.value),
                          }),
                        },
                        { x, y: 0, width: w },
                      );
                    }}
                    onFocus={() => {
                      setFocus({
                        ...focus,
                        place: branch.place,
                        purpose: undefined,
                      });
                      show(
                        {
                          value: money(branch.value, units),
                          label: branch.label,
                        },
                        { x, y: 0, width: w },
                      );
                    }}
                    onBlur={() => setTip(null)}
                    onClick={() => setZoom(zoom ? undefined : branch.place)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        setZoom(zoom ? undefined : branch.place);
                      }
                    }}
                  >
                    <rect
                      x={x}
                      width={Math.max(w, 1)}
                      height={rowTop}
                      rx={4}
                      fill={placeColor[branch.place]}
                    />
                    {w > 96 && (
                      <text
                        x={x + 10}
                        y={rowTop / 2 + 4}
                        className="fill-white text-sm font-medium"
                      >
                        {branch.label}
                        {w > 220 && (
                          <tspan className="num" opacity={0.85} dx={8}>
                            {formatUnits(branch.value, units.decimals, {
                              maxFraction: 0,
                              minFraction: 0,
                            })}
                          </tspan>
                        )}
                      </text>
                    )}
                  </g>
                  {leaves.map(({ item: leaf, x: lx, width: lw }) => {
                    const held = heldPurposes.has(leaf.purpose);
                    const fill = held
                      ? `url(#hatch-${branch.place})`
                      : placeColor[branch.place];
                    return (
                      <g
                        key={leaf.purpose}
                        tabIndex={0}
                        role="img"
                        aria-label={`${branch.label}, ${leaf.label}: ${money(leaf.value, units)}`}
                        className="outline-none"
                        opacity={dim(branch.place, leaf.purpose)}
                        onPointerEnter={() => {
                          setFocus({
                            ...focus,
                            place: branch.place,
                            purpose: leaf.purpose,
                          });
                          show(
                            {
                              value: money(leaf.value, units),
                              label: `${branch.label} · ${leaf.label}`,
                              detail: held
                                ? t('Held back, not spendable')
                                : t('Usable'),
                            },
                            { x: x + lx, y: rowTop + 2, width: lw },
                          );
                        }}
                        onFocus={() => {
                          setFocus({
                            ...focus,
                            place: branch.place,
                            purpose: leaf.purpose,
                          });
                          show(
                            {
                              value: money(leaf.value, units),
                              label: `${branch.label} · ${leaf.label}`,
                            },
                            { x: x + lx, y: rowTop + 2, width: lw },
                          );
                        }}
                        onBlur={() => setTip(null)}
                      >
                        <rect
                          x={x + lx}
                          y={rowTop + 2}
                          width={Math.max(lw, 1)}
                          height={rowLeaf}
                          rx={4}
                          fill={fill}
                        />
                        {lw > 120 && (
                          <text
                            x={x + lx + 8}
                            y={rowTop + 2 + rowLeaf / 2 + 4}
                            className={cn(
                              'text-xs font-medium',
                              held ? 'fill-foreground' : 'fill-white',
                            )}
                          >
                            {leaf.label}
                          </text>
                        )}
                      </g>
                    );
                  })}
                </g>
              );
            })}
          </svg>
        )}
        <Tip tip={tip} />
      </div>

      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-muted-foreground">
        {branches.map((branch) => (
          <li key={branch.place}>
            <button
              type="button"
              className={cn(
                'inline-flex items-center gap-1.5 rounded-sm hover:text-foreground',
                place === branch.place && 'text-foreground',
              )}
              onPointerEnter={() =>
                setFocus({ ...focus, place: branch.place, purpose: undefined })
              }
              onPointerLeave={() => setFocus({ ...focus, place: undefined })}
              onClick={() =>
                setZoom(zoom === branch.place ? undefined : branch.place)
              }
            >
              <Swatch color={placeColor[branch.place]} />
              {branch.label}
              <span className="num text-xs text-subtle-foreground">
                {share(branch.value)}
              </span>
            </button>
          </li>
        ))}
        <li className="ml-auto inline-flex items-center gap-3 text-xs">
          <span className="inline-flex items-center gap-1.5">
            <Swatch color="hsl(var(--muted-foreground))" /> {t('Usable')}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Swatch color="hsl(var(--muted-foreground))" hatched />{' '}
            {t('Held back')}
          </span>
        </li>
      </ul>

      <TableToggle>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="py-1 font-medium">{t('Location')}</th>
              <th className="py-1 font-medium">{t('Purpose')}</th>
              <th className="py-1 text-right font-medium">{t('Amount')}</th>
            </tr>
          </thead>
          <tbody>
            {branches.flatMap((branch) =>
              branch.children.map((leaf) => (
                <tr
                  key={`${branch.place}-${leaf.purpose}`}
                  className="border-t"
                >
                  <td className="py-1">{branch.label}</td>
                  <td className="py-1">{leaf.label}</td>
                  <td className="num py-1 text-right">
                    {money(leaf.value, units)}
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </TableToggle>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 2. Safe health: balance against buffer and target                    */
/* ------------------------------------------------------------------ */

export function SafeBullets({
  units,
  wallets,
}: {
  units: Units;
  wallets: TreasuryWallet[];
}) {
  const { focus, place, setFocus, selected, setSelected } = useFocus();
  const rows = wallets.filter(
    (wallet): wallet is TreasuryWallet & { role: 'T' | 'O1' | 'O2' } =>
      wallet.role !== 'GUARDIAN',
  );
  return (
    <ul className="grid gap-4">
      {rows.map((wallet) => {
        const n = (value: string) => toNumber(value, units);
        const balance = n(wallet.balance);
        const buffer = n(wallet.buffer);
        const target = n(wallet.target);
        const scale = Math.max(balance, target, buffer, 1) * 1.1;
        const pct = (value: number) => `${(value / scale) * 100}%`;
        const below = balance < buffer;
        const short = !below && balance < target;
        const dimmed = place && place !== wallet.role;
        return (
          <li
            key={wallet.role}
            className={cn('transition-opacity', dimmed && 'opacity-30')}
            onPointerEnter={() =>
              setFocus({ ...focus, place: wallet.role, purpose: undefined })
            }
            onPointerLeave={() => setFocus({ ...focus, place: undefined })}
          >
            <button
              type="button"
              className="block w-full rounded-sm text-left"
              aria-pressed={selected === wallet.role}
              onClick={() =>
                setSelected(selected === wallet.role ? undefined : wallet.role)
              }
            >
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="flex items-center gap-1.5 font-medium">
                  <Swatch color={placeColor[wallet.role]} />
                  {wallet.label}
                </span>
                <span className="flex items-center gap-1.5">
                  {below && (
                    <CircleAlert
                      className="size-3.5 text-danger"
                      aria-label={t('Below minimum buffer')}
                    />
                  )}
                  {short && (
                    <TriangleAlert
                      className="size-3.5 text-warning"
                      aria-label={t('Below target')}
                    />
                  )}
                  <span className="num font-medium">
                    {formatUnits(wallet.balance, units.decimals)}
                  </span>
                </span>
              </div>
              <div
                className="relative mt-1.5 h-3 rounded-sm bg-muted"
                role="meter"
                aria-label={wallet.label}
                aria-valuemin={0}
                aria-valuemax={target}
                aria-valuenow={balance}
                aria-valuetext={t(
                  '{{balance}}, buffer {{buffer}}, target {{target}}',
                  {
                    balance: money(wallet.balance, units),
                    buffer: money(wallet.buffer, units),
                    target: money(wallet.target, units),
                  },
                )}
              >
                <div
                  className="absolute inset-y-0 left-0 rounded-sm"
                  style={{
                    width: pct(balance),
                    background: placeColor[wallet.role],
                  }}
                />
                <div
                  className="absolute -inset-y-1 w-0.5 rounded-full bg-foreground"
                  style={{ left: pct(buffer) }}
                  title={t('Minimum buffer')}
                />
                <div
                  className="absolute -inset-y-1 w-0.5 rounded-full border border-foreground bg-surface"
                  style={{ left: pct(target) }}
                  title={t('Target')}
                />
              </div>
            </button>
          </li>
        );
      })}
      <li className="flex items-center gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span
            className="h-3 w-0.5 rounded-full bg-foreground"
            aria-hidden="true"
          />
          {t('Minimum buffer')}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="h-3 w-0.5 rounded-full border border-foreground bg-surface"
            aria-hidden="true"
          />
          {t('Target')}
        </span>
      </li>
    </ul>
  );
}

/* ------------------------------------------------------------------ */
/* 3. Runway: projected balance over outflows, one shared day axis      */
/* ------------------------------------------------------------------ */

const coveredByReserve = new Set(['Approved', 'Scheduled']);

export function RunwayChart({
  forecast,
  includeDrafts,
  requests,
  requestHref,
  units,
  walletLabel,
}: {
  forecast: Forecast;
  includeDrafts: boolean;
  requests: PaymentRequest[];
  requestHref: (id: string) => string;
  units: Units;
  walletLabel: string;
}) {
  const { focus, place, setFocus } = useFocus();
  const navigate = useNavigate();
  const [ref, width] = useWidth<HTMLDivElement>();
  const days = forecast.days;

  const perDay = days.map((day) =>
    requests
      .filter(
        (request) =>
          request.dueDate.slice(0, 10) === day.date &&
          (['Approved', 'Scheduled', 'AwaitingApproval'].includes(
            request.status,
          ) ||
            (includeDrafts && request.status === 'Draft')),
      )
      .sort((a, b) => Number(BigInt(b.amount) - BigInt(a.amount))),
  );

  const n = (value: string) => toNumber(value, units);
  const balances = days.map((day) => n(day.balance));
  const buffer = days[0] ? n(days[0].buffer) : 0;
  const outflows = days.map((day) => n(day.outflow));

  const pad = { left: 44, right: 12 };
  const lineH = 150;
  const gapH = 22;
  const barH = 96;
  const axisH = 22;
  const height = lineH + gapH + barH + axisH;
  const plotW = Math.max(0, width - pad.left - pad.right);
  const band = days.length ? plotW / days.length : 0;
  const cx = (index: number) => pad.left + band * index + band / 2;

  const hi = Math.max(...balances, buffer, 1);
  const lo = Math.min(...balances, 0);
  const span = hi - lo || 1;
  const yLine = (value: number) => 8 + ((hi - value) / span) * (lineH - 16);
  const maxOut = Math.max(...outflows, 1);
  const barTop = lineH + gapH;
  const yBar = (value: number) => (value / maxOut) * (barH - 4);

  const breach = days.findIndex((day) => n(day.balance) < n(day.buffer));
  const path = balances
    .map((value, index) => `${index ? 'L' : 'M'}${cx(index)},${yLine(value)}`)
    .join(' ');
  const ticks = [lo, (lo + hi) / 2, hi];

  const active = focus.day;
  const reserveFocus = focus.purpose === 'reserve';
  const runwayDimmed = place && place !== 'O1';
  const activeDay = active !== undefined ? days[active] : undefined;
  const short = (value: number) =>
    Math.abs(value) >= 1000
      ? `${Math.round(value / 100) / 10}k`
      : `${Math.round(value)}`;

  return (
    <div
      className={cn(
        'grid gap-3 transition-opacity',
        runwayDimmed && 'opacity-40',
      )}
    >
      <div
        ref={ref}
        className="relative"
        onPointerLeave={() => setFocus({ ...focus, day: undefined })}
      >
        {width > 0 && (
          <svg
            width={width}
            height={height}
            role="img"
            aria-label={t(
              'Projected {{wallet}} balance for the next 7 days above the payments due each day.',
              { wallet: walletLabel },
            )}
            className="block"
          >
            <HatchDefs ids={[['hatch-runway', 'var(--chart-3)']]} />
            {/* balance panel */}
            {ticks.map((tick) => (
              <g key={tick}>
                <line
                  x1={pad.left}
                  x2={width - pad.right}
                  y1={yLine(tick)}
                  y2={yLine(tick)}
                  stroke="hsl(var(--border))"
                />
                <text
                  x={pad.left - 6}
                  y={yLine(tick) + 4}
                  textAnchor="end"
                  className="num fill-muted-foreground text-xs"
                >
                  {short(tick)}
                </text>
              </g>
            ))}
            {buffer > lo && (
              <rect
                x={pad.left}
                width={plotW}
                y={yLine(buffer)}
                height={Math.max(0, yLine(lo) - yLine(buffer))}
                fill="hsl(var(--danger-muted))"
              />
            )}
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={yLine(buffer)}
              y2={yLine(buffer)}
              stroke="hsl(var(--danger))"
              strokeDasharray="4 3"
            />
            <text
              x={width - pad.right}
              y={yLine(buffer) - 5}
              textAnchor="end"
              className="fill-danger-foreground text-xs"
            >
              {t('Minimum buffer')}
            </text>
            <path
              d={path}
              fill="none"
              stroke="var(--chart-3)"
              strokeWidth={2}
            />
            {balances.map((value, index) => (
              <circle
                key={index}
                cx={cx(index)}
                cy={yLine(value)}
                r={active === index || index === breach ? 5 : 3}
                fill={
                  index === breach ? 'hsl(var(--danger))' : 'var(--chart-3)'
                }
                stroke="hsl(var(--surface))"
                strokeWidth={2}
              />
            ))}

            {/* outflow panel: one segment per invoice */}
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={barTop + barH}
              y2={barTop + barH}
              stroke="hsl(var(--border-strong))"
            />
            <text
              x={pad.left - 6}
              y={barTop + 10}
              textAnchor="end"
              className="num fill-muted-foreground text-xs"
            >
              {short(maxOut)}
            </text>
            {perDay.map((items, index) => {
              let y = barTop + barH;
              const w = Math.min(band * 0.56, 40);
              return items.map((request) => {
                const h = Math.max(2, yBar(n(request.amount)) - 2);
                y -= h + 2;
                const covered = coveredByReserve.has(request.status);
                const draft = request.status === 'Draft';
                const dim =
                  (reserveFocus && !covered) ||
                  (active !== undefined && active !== index);
                return (
                  <rect
                    key={request.id}
                    x={cx(index) - w / 2}
                    y={y + 2}
                    width={w}
                    height={h}
                    rx={3}
                    fill={
                      draft
                        ? 'none'
                        : covered
                          ? 'var(--chart-3)'
                          : 'url(#hatch-runway)'
                    }
                    stroke={draft ? 'var(--chart-3)' : undefined}
                    strokeDasharray={draft ? '3 2' : undefined}
                    pointerEvents="all"
                    opacity={dim ? 0.3 : 1}
                    className="cursor-pointer"
                    onClick={() => navigate(requestHref(request.id))}
                  >
                    <title>{`${request.vendorName} · ${money(request.amount, units)}${request.status === 'Draft' ? ` · ${t('Draft')}` : ''}`}</title>
                  </rect>
                );
              });
            })}

            {/* shared crosshair + hit areas spanning both panels */}
            {active !== undefined && (
              <line
                x1={cx(active)}
                x2={cx(active)}
                y1={0}
                y2={barTop + barH}
                stroke="hsl(var(--foreground))"
                strokeOpacity={0.35}
              />
            )}
            {days.map((day, index) => (
              <g key={day.date}>
                <text
                  x={cx(index)}
                  y={height - 6}
                  textAnchor="middle"
                  className={cn(
                    'text-xs',
                    active === index
                      ? 'fill-foreground font-medium'
                      : 'fill-muted-foreground',
                  )}
                >
                  {index === 0
                    ? t('Today')
                    : format(new Date(`${day.date}T00:00:00Z`), 'EEE d')}
                </text>
                <rect
                  x={pad.left + band * index}
                  y={0}
                  width={band}
                  height={barTop + barH}
                  fill="transparent"
                  onPointerEnter={() => setFocus({ ...focus, day: index })}
                />
              </g>
            ))}
          </svg>
        )}
      </div>

      <div className="flex min-h-14 flex-wrap items-start gap-x-6 gap-y-2 rounded-md border bg-surface-muted px-3 py-2 text-sm">
        {activeDay ? (
          <>
            <div>
              <p className="text-xs text-muted-foreground">
                {active === 0 ? t('Today') : dayLabel(activeDay.date)}
              </p>
              <p className="num font-semibold">
                {money(activeDay.balance, units)}
              </p>
            </div>
            <ul className="flex flex-wrap gap-x-4 gap-y-1">
              {perDay[active ?? 0].length === 0 ? (
                <li className="text-muted-foreground">{t('Nothing due')}</li>
              ) : (
                perDay[active ?? 0].map((request) => (
                  <li key={request.id} className="flex items-center gap-1.5">
                    <Swatch
                      color="var(--chart-3)"
                      hatched={
                        !coveredByReserve.has(request.status) &&
                        request.status !== 'Draft'
                      }
                      dashed={request.status === 'Draft'}
                    />
                    <span>{request.vendorName}</span>
                    {request.status === 'Draft' && (
                      <span className="text-xs text-muted-foreground">
                        {t('Draft')}
                      </span>
                    )}
                    <span className="num text-muted-foreground">
                      −{formatUnits(request.amount, units.decimals)}
                    </span>
                  </li>
                ))
              )}
            </ul>
          </>
        ) : (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-muted-foreground">
            {breach >= 0 ? (
              <span className="inline-flex items-center gap-1.5 text-danger-foreground">
                <CircleAlert className="size-4" aria-hidden="true" />
                {t('Below buffer on {{day}} without a refill', {
                  day: dayLabel(days[breach].date),
                })}
              </span>
            ) : (
              <span>{t('Stays above its buffer all week')}</span>
            )}
            <span className="inline-flex items-center gap-1.5 text-xs">
              <Swatch color="var(--chart-3)" /> {t('Approved')}
            </span>
            <span className="inline-flex items-center gap-1.5 text-xs">
              <Swatch color="var(--chart-3)" hatched /> {t('Awaiting approval')}
            </span>
            {includeDrafts && (
              <span className="inline-flex items-center gap-1.5 text-xs">
                <Swatch color="var(--chart-3)" dashed /> {t('Drafts included')}
              </span>
            )}
          </div>
        )}
      </div>

      <TableToggle>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="py-1 font-medium">{t('Day')}</th>
              <th className="py-1 text-right font-medium">{t('Due')}</th>
              <th className="py-1 text-right font-medium">
                {t('Projected balance')}
              </th>
            </tr>
          </thead>
          <tbody>
            {days.map((day) => (
              <tr key={day.date} className="border-t">
                <td className="py-1">{dayLabel(day.date)}</td>
                <td className="num py-1 text-right">
                  {money(day.outflow, units)}
                </td>
                <td className="num py-1 text-right">
                  {money(day.balance, units)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableToggle>
    </div>
  );
}

function dayLabel(date: string) {
  return format(new Date(`${date}T00:00:00Z`), 'EEE, MMM d');
}

/* ------------------------------------------------------------------ */
/* 4. Today's budget: used, what is due today, and the daily limit      */
/* ------------------------------------------------------------------ */

export function BudgetBullets({
  budgets,
  dueToday,
  units,
}: {
  budgets: Budget[];
  dueToday: string;
  units: Units;
}) {
  const { focus } = useFocus();
  const todayActive = focus.day === 0;
  return (
    <ul className="grid gap-4">
      {budgets.map((budget) => {
        const n = (value: string) => toNumber(value, units);
        const limit = Math.max(n(budget.dailyLimit), 1);
        const used = n(budget.usedToday);
        const due = budget.action === 'PAY' ? n(dueToday) : 0;
        const pct = (value: number) =>
          `${Math.min(100, (value / limit) * 100)}%`;
        const over = used + due > limit;
        return (
          <li key={budget.action}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="font-medium">
                {budget.action === 'PAY' ? t('Payments') : t('Refills')}
              </span>
              <span className="num">
                <span className="font-medium">
                  {formatUnits(budget.usedToday, units.decimals)}
                </span>
                <span className="text-muted-foreground">
                  {' '}
                  / {formatUnits(budget.dailyLimit, units.decimals)}
                </span>
              </span>
            </div>
            <div
              className="relative mt-1.5 flex h-3 overflow-hidden rounded-sm bg-muted"
              role="meter"
              aria-label={
                budget.action === 'PAY'
                  ? t('Payments today')
                  : t('Refills today')
              }
              aria-valuemin={0}
              aria-valuemax={limit}
              aria-valuenow={used}
            >
              <div className="h-full bg-primary" style={{ width: pct(used) }} />
              {due > 0 && (
                <div
                  className={cn(
                    'h-full transition-opacity',
                    !todayActive && 'opacity-70',
                  )}
                  style={{
                    width: pct(due),
                    marginLeft: 2,
                    background:
                      'repeating-linear-gradient(45deg, hsl(var(--primary)) 0 2px, transparent 2px 4px)',
                  }}
                  title={t('Due today')}
                />
              )}
            </div>
            {over && (
              <p className="mt-1 flex items-center gap-1 text-xs text-warning-foreground">
                <TriangleAlert className="size-3.5" aria-hidden="true" />
                {t('Today’s due payments exceed what is left of the limit')}
              </p>
            )}
          </li>
        );
      })}
      <li className="flex items-center gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Swatch color="hsl(var(--primary))" /> {t('Used')}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color="hsl(var(--primary))" hatched /> {t('Due today')}
        </span>
      </li>
    </ul>
  );
}
