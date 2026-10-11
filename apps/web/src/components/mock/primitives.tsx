import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from 'react';
import { forwardRef, useId } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CircleHelp,
  Clock3,
  Info,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { NavLink } from 'react-router-dom';

import { cn } from '@/lib/utils';

export type StatusTone =
  | 'success'
  | 'info'
  | 'attention'
  | 'danger'
  | 'neutral'
  | 'pending';

const statusStyles: Record<StatusTone, string> = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  info: 'border-blue-200 bg-blue-50 text-blue-800',
  attention: 'border-amber-200 bg-amber-50 text-amber-800',
  danger: 'border-rose-200 bg-rose-50 text-rose-800',
  neutral: 'border-slate-200 bg-slate-100 text-slate-700',
  pending: 'border-violet-200 bg-violet-50 text-violet-800',
};

const statusIcons = {
  success: Check,
  info: Info,
  attention: AlertTriangle,
  danger: XCircle,
  neutral: CircleHelp,
  pending: Clock3,
} satisfies Record<StatusTone, typeof Check>;

export interface BrandMarkProps {
  compact?: boolean;
  className?: string;
  showDescriptor?: boolean;
}

export function BrandMark({
  compact = false,
  className,
  showDescriptor = false,
}: BrandMarkProps) {
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-3', className)}>
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-700 text-white shadow-lg shadow-blue-900/15">
        <ShieldCheck aria-hidden="true" size={21} strokeWidth={2.2} />
      </span>
      {!compact && (
        <span className="min-w-0 leading-tight">
          <span className="block truncate text-[15px] font-bold tracking-[-0.04em] text-slate-950">
            Treasury<span className="text-blue-700">Pilot</span>
          </span>
          {showDescriptor && (
            <span className="mt-1 block text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400">
              Treasury operations
            </span>
          )}
        </span>
      )}
    </span>
  );
}

export type MockButtonVariant =
  | 'primary'
  | 'secondary'
  | 'quiet'
  | 'danger'
  | 'soft';
export type MockButtonSize = 'sm' | 'md' | 'lg' | 'icon';

export interface MockButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: MockButtonVariant;
  size?: MockButtonSize;
  fullWidth?: boolean;
}

const buttonVariants: Record<MockButtonVariant, string> = {
  primary:
    'border border-blue-700 bg-blue-700 text-white shadow-sm shadow-blue-900/10 hover:border-blue-800 hover:bg-blue-800',
  secondary:
    'border border-slate-200 bg-white text-slate-700 shadow-sm hover:border-blue-200 hover:bg-blue-50 hover:text-blue-800',
  quiet:
    'border border-transparent bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900',
  danger: 'border border-rose-200 bg-white text-rose-700 hover:bg-rose-50',
  soft: 'border border-blue-100 bg-blue-50 text-blue-800 hover:border-blue-200 hover:bg-blue-100',
};

const buttonSizes: Record<MockButtonSize, string> = {
  sm: 'h-9 rounded-lg px-3 text-xs',
  md: 'h-10 rounded-xl px-4 text-sm',
  lg: 'h-11 rounded-xl px-5 text-sm',
  icon: 'size-10 rounded-xl p-0',
};

export const MockButton = forwardRef<HTMLButtonElement, MockButtonProps>(
  (
    {
      className,
      variant = 'secondary',
      size = 'md',
      fullWidth = false,
      type = 'button',
      ...props
    },
    ref,
  ) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        'inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50',
        buttonVariants[variant],
        buttonSizes[size],
        fullWidth && 'w-full',
        className,
      )}
      {...props}
    />
  ),
);
MockButton.displayName = 'MockButton';

export interface IconButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  size?: 'sm' | 'md';
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ label, size = 'md', className, type = 'button', ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        'inline-grid shrink-0 place-items-center rounded-xl text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2',
        size === 'sm' ? 'size-8' : 'size-10',
        className,
      )}
      {...props}
    />
  ),
);
IconButton.displayName = 'IconButton';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

export function Card({ padding = 'sm', className, ...props }: CardProps) {
  const pad = {
    none: 'p-0',
    sm: 'p-4',
    md: 'p-5 sm:p-6',
    lg: 'p-6 sm:p-7',
  }[padding];

  return (
    <div
      className={cn(
        'rounded-2xl border border-slate-200/80 bg-white shadow-[0_8px_30px_rgba(25,49,91,0.045)]',
        pad,
        className,
      )}
      {...props}
    />
  );
}

export interface StatusBadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: StatusTone;
  icon?: boolean;
  dot?: boolean;
}

export function StatusBadge({
  tone = 'neutral',
  icon = false,
  dot = false,
  className,
  children,
  ...props
}: StatusBadgeProps) {
  const StatusIcon = statusIcons[tone];
  return (
    <span
      className={cn(
        'inline-flex max-w-full items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-semibold leading-4',
        statusStyles[tone],
        className,
      )}
      {...props}
    >
      {dot ? (
        <span
          aria-hidden="true"
          className="size-1.5 shrink-0 rounded-full bg-current"
        />
      ) : null}
      {icon ? (
        <StatusIcon aria-hidden="true" className="shrink-0" size={13} />
      ) : null}
      <span className="truncate">{children}</span>
    </span>
  );
}

export interface SectionHeadingProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  description?: string;
  action?: ReactNode;
  level?: 2 | 3;
}

export function SectionHeading({
  title,
  description,
  action,
  level = 2,
  className,
  ...props
}: SectionHeadingProps) {
  const Heading = level === 2 ? 'h2' : 'h3';
  return (
    <div
      className={cn(
        'mb-5 flex flex-wrap items-start justify-between gap-3',
        className,
      )}
      {...props}
    >
      <div>
        <Heading className="text-sm font-bold tracking-[-0.02em] text-slate-900 sm:text-base">
          {title}
        </Heading>
        {description && (
          <p className="mt-1 text-xs leading-5 text-slate-500 sm:text-sm">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

export interface PageHeadingProps extends HTMLAttributes<HTMLDivElement> {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeading({
  eyebrow,
  title,
  description,
  actions,
  className,
  ...props
}: PageHeadingProps) {
  return (
    <header
      className={cn(
        'mb-6 flex flex-col justify-between gap-4 sm:mb-8 sm:flex-row sm:items-end',
        className,
      )}
      {...props}
    >
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.14em] text-blue-700">
            {eyebrow}
          </p>
        )}
        <h1 className="text-2xl font-bold tracking-[-0.045em] text-slate-950 sm:text-[30px]">
          {title}
        </h1>
        {description && (
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      )}
    </header>
  );
}

export interface MetricCardProps {
  label: string;
  value: string;
  detail?: string;
  trend?: string;
  tone?: StatusTone;
  icon?: ReactNode;
}

export function MetricCard({
  label,
  value,
  detail,
  trend,
  tone = 'neutral',
  icon,
}: MetricCardProps) {
  return (
    <Card className="min-h-36 overflow-hidden">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-semibold text-slate-500 sm:text-sm">
          {label}
        </p>
        {icon && (
          <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700">
            {icon}
          </span>
        )}
      </div>
      <p className="mt-4 text-[26px] font-bold leading-none tracking-[-0.05em] text-slate-950 sm:text-[30px]">
        {value}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1">
        {trend && (
          <StatusBadge tone={tone} dot>
            {trend}
          </StatusBadge>
        )}
        {detail && <span className="text-[11px] text-slate-500">{detail}</span>}
      </div>
    </Card>
  );
}

export interface MockInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  error?: string;
}

export const MockInput = forwardRef<HTMLInputElement, MockInputProps>(
  ({ label, hint, error, id, className, required, ...props }, ref) => {
    const inputId =
      id ?? props.name ?? label.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    const hintId = `${inputId}-hint`;
    const errorId = `${inputId}-error`;
    return (
      <div className="grid gap-1.5">
        <label
          htmlFor={inputId}
          className="text-xs font-semibold text-slate-700"
        >
          {label}
          {required ? (
            <span className="ml-1 text-rose-600" aria-hidden="true">
              *
            </span>
          ) : null}
        </label>
        <input
          ref={ref}
          id={inputId}
          required={required}
          aria-invalid={Boolean(error)}
          aria-describedby={
            [hint && hintId, error && errorId].filter(Boolean).join(' ') ||
            undefined
          }
          className={cn(
            'h-10 min-w-0 rounded-xl border bg-white px-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400',
            error
              ? 'border-rose-300 focus:border-rose-500 focus:ring-rose-100'
              : 'border-slate-200',
            className,
          )}
          {...props}
        />
        {hint && !error && (
          <p id={hintId} className="text-xs leading-5 text-slate-500">
            {hint}
          </p>
        )}
        {error && (
          <p id={errorId} className="text-xs leading-5 text-rose-700">
            {error}
          </p>
        )}
      </div>
    );
  },
);
MockInput.displayName = 'MockInput';

export interface MockSelectProps
  extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}

export const MockSelect = forwardRef<HTMLSelectElement, MockSelectProps>(
  ({ label, hint, error, id, className, children, ...props }, ref) => {
    const selectId =
      id ?? props.name ?? label.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    const hintId = `${selectId}-hint`;
    const errorId = `${selectId}-error`;
    return (
      <div className="grid gap-1.5">
        <label
          htmlFor={selectId}
          className="text-xs font-semibold text-slate-700"
        >
          {label}
        </label>
        <select
          ref={ref}
          id={selectId}
          aria-invalid={Boolean(error)}
          aria-describedby={
            [hint && hintId, error && errorId].filter(Boolean).join(' ') ||
            undefined
          }
          className={cn(
            'h-10 min-w-0 rounded-xl border bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400',
            error
              ? 'border-rose-300 focus:border-rose-500 focus:ring-rose-100'
              : 'border-slate-200',
            className,
          )}
          {...props}
        >
          {children}
        </select>
        {hint && !error && (
          <p id={hintId} className="text-xs leading-5 text-slate-500">
            {hint}
          </p>
        )}
        {error && (
          <p id={errorId} className="text-xs leading-5 text-rose-700">
            {error}
          </p>
        )}
      </div>
    );
  },
);
MockSelect.displayName = 'MockSelect';

export interface MockToggleProps {
  label: string;
  description?: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  className?: string;
}

export function MockToggle({
  label,
  description,
  checked,
  onCheckedChange,
  disabled = false,
  className,
}: MockToggleProps) {
  return (
    <div className={cn('flex items-center justify-between gap-4', className)}>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-800">{label}</p>
        {description && (
          <p className="mt-0.5 text-xs leading-5 text-slate-500">
            {description}
          </p>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onCheckedChange(!checked)}
        className={cn(
          'relative h-6 w-11 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50',
          checked ? 'bg-blue-700' : 'bg-slate-300',
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            'absolute top-0.5 size-5 rounded-full bg-white shadow-sm transition-transform',
            checked ? 'translate-x-[22px]' : 'translate-x-0.5',
          )}
        />
      </button>
    </div>
  );
}

export function SafetyNotice({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="note"
      className={cn(
        'flex items-start gap-3 rounded-xl border border-blue-100 bg-blue-50/80 p-4 text-blue-950',
        className,
      )}
      {...props}
    >
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-white text-blue-700 shadow-sm">
        <ShieldCheck aria-hidden="true" size={17} />
      </span>
      <div className="min-w-0 text-xs leading-5 sm:text-sm">
        <p className="font-bold">Human approval required for every payment</p>
        <p className="mt-1 text-blue-900/75">
          Recommendations are read-only. Organization policy and on-chain Safe
          rules remain the authority for execution.
        </p>
      </div>
    </div>
  );
}

export type BadgeTone = 'blue' | 'green' | 'amber' | 'red' | 'slate';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

const badgeToneMap: Record<BadgeTone, StatusTone> = {
  blue: 'info',
  green: 'success',
  amber: 'attention',
  red: 'danger',
  slate: 'neutral',
};

export function Badge({ tone = 'slate', ...props }: BadgeProps) {
  return <StatusBadge tone={badgeToneMap[tone]} {...props} />;
}

export type ActionButtonProps = MockButtonProps;

export function ActionButton({
  variant = 'primary',
  ...props
}: ActionButtonProps) {
  return <MockButton variant={variant} {...props} />;
}

export interface CardTitleProps {
  title: string;
  detail?: string;
  action?: ReactNode;
}

export function CardTitle({ title, detail, action }: CardTitleProps) {
  return <SectionHeading title={title} description={detail} action={action} />;
}

export interface StatCardProps {
  label: string;
  value: string;
  meta: string;
  icon: LucideIcon;
  tone?: 'blue' | 'green' | 'amber';
}

export function StatCard({
  label,
  value,
  meta,
  icon: Icon,
  tone = 'blue',
}: StatCardProps) {
  const toneMap: Record<NonNullable<StatCardProps['tone']>, StatusTone> = {
    blue: 'info',
    green: 'success',
    amber: 'attention',
  };

  return (
    <MetricCard
      label={label}
      value={value}
      detail={meta}
      tone={toneMap[tone]}
      icon={<Icon aria-hidden="true" size={17} />}
    />
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400">
      {children}
    </p>
  );
}

export function InlineLink({
  to,
  children,
}: {
  to: string;
  children: ReactNode;
}) {
  return (
    <NavLink
      to={to}
      className="inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:text-blue-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
    >
      {children}
      <ArrowRight aria-hidden="true" size={14} />
    </NavLink>
  );
}

export function MiniChart({
  variant = 'balance',
  range = '7 days',
}: {
  variant?: 'balance' | 'forecast';
  range?: '7 days' | '30 days';
}) {
  const chartId = useId().replace(/:/g, '');
  const points =
    variant === 'balance'
      ? '0,105 55,91 110,96 165,73 220,79 275,57 330,61 385,42 440,46 495,24 550,29 605,8'
      : range === '30 days'
        ? '0,86 55,82 110,77 165,72 220,66 275,61 330,57 385,51 440,46 495,40 550,35 605,31'
        : '0,92 55,83 110,88 165,69 220,72 275,53 330,61 385,45 440,48 495,27 550,35 605,16';
  const fillPoints = `0,140 ${points} 605,140`;
  const gradientId = `mock-chart-fill-${variant}-${chartId}`;

  return (
    <div
      className="w-full"
      role="img"
      aria-label={
        variant === 'balance'
          ? 'Treasury balance increased over the last six months, with lower monthly outflows'
          : `Projected available liquidity remains above the required reserve for ${range}`
      }
    >
      <svg
        viewBox="0 0 605 150"
        className="h-[166px] w-full overflow-visible"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity=".16" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[25, 65, 105, 140].map((y) => (
          <line
            key={y}
            x1="0"
            x2="605"
            y1={y}
            y2={y}
            stroke="#e9eef6"
            strokeDasharray="3 6"
          />
        ))}
        <polygon points={fillPoints} fill={`url(#${gradientId})`} />
        <polyline
          points={points}
          fill="none"
          stroke="#346af2"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        <polyline
          points="0,126 55,122 110,119 165,119 220,115 275,111 330,113 385,103 440,105 495,98 550,91 605,82"
          fill="none"
          stroke="#f6a35e"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="mt-1 flex justify-between pl-1 text-[10px] text-slate-400">
        <span>May</span>
        <span>Jun</span>
        <span>Jul</span>
        <span>Aug</span>
        <span>Sep</span>
        <span>Oct</span>
      </div>
    </div>
  );
}
