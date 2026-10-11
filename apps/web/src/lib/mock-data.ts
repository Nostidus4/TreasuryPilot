import type { LucideIcon } from 'lucide-react';
import { FileText, LayoutDashboard, Sparkles, WalletCards } from 'lucide-react';

export type MockPageId = 'dashboard' | 'invoices' | 'plans' | 'treasury';

export interface MockNavigationItem {
  id: MockPageId;
  label: string;
  to: string;
  icon: LucideIcon;
  group: 'workspace' | 'treasury';
}

export interface MockWorkspace {
  name: string;
  initials: string;
  network: string;
  environment: string;
}

export interface MockUser {
  name: string;
  initials: string;
  role: string;
}

export const mockWorkspace: MockWorkspace = {
  name: 'Acme Finance',
  initials: 'AF',
  network: 'Sepolia TEST',
  environment: 'Fictional preview',
};

export const mockUser: MockUser = {
  name: 'Avery Lin',
  initials: 'AL',
  role: 'Treasury operator',
};

export const mockNavigation: readonly MockNavigationItem[] = [
  {
    id: 'dashboard',
    label: 'Overview',
    to: '/mock',
    icon: LayoutDashboard,
    group: 'workspace',
  },
  {
    id: 'invoices',
    label: 'Invoices & approvals',
    to: '/mock/invoices',
    icon: FileText,
    group: 'workspace',
  },
  {
    id: 'plans',
    label: 'Payment plan',
    to: '/mock/plans',
    icon: Sparkles,
    group: 'treasury',
  },
  {
    id: 'treasury',
    label: 'Treasury & liquidity',
    to: '/mock/treasury',
    icon: WalletCards,
    group: 'treasury',
  },
];

export type InvoiceStatus =
  | 'Approved'
  | 'Needs approval'
  | 'In review'
  | 'Scheduled'
  | 'Paid';

export interface MockInvoice {
  vendor: string;
  initials: string;
  invoice: string;
  amount: number;
  due: string;
  status: InvoiceStatus;
  risk: 'Low' | 'Review' | 'High';
  note: string;
  payee: string;
}

export const mockInvoices: readonly MockInvoice[] = [
  {
    vendor: 'Acurast Cloud',
    initials: 'AC',
    invoice: 'AC-2026-104',
    amount: 1450,
    due: 'Oct 12, 2026',
    status: 'Approved',
    risk: 'Low',
    note: 'Allowlisted payee · standard terms confirmed',
    payee: '0x41a8…92e1',
  },
  {
    vendor: 'Northstar Analytics',
    initials: 'NA',
    invoice: 'NSA-2026-288',
    amount: 875,
    due: 'Oct 13, 2026',
    status: 'Needs approval',
    risk: 'Low',
    note: 'New request · amount matches vendor history',
    payee: '0xc820…10b4',
  },
  {
    vendor: 'Cloudscale Systems',
    initials: 'CS',
    invoice: 'CS-2026-051',
    amount: 2350,
    due: 'Oct 14, 2026',
    status: 'In review',
    risk: 'High',
    note: 'Above the 2,000 USDC TEST per-payment mandate cap',
    payee: '0x8b20…77d2',
  },
  {
    vendor: 'Meridian Security',
    initials: 'MS',
    invoice: 'MS-2026-033',
    amount: 1990,
    due: 'Oct 16, 2026',
    status: 'Scheduled',
    risk: 'Review',
    note: 'Approved · waits for daily limit window',
    payee: '0x0d74…a6c3',
  },
  {
    vendor: 'Index Harbor',
    initials: 'IH',
    invoice: 'IH-2026-097',
    amount: 620,
    due: 'Oct 18, 2026',
    status: 'Paid',
    risk: 'Low',
    note: 'Settled in the Sepolia TEST fixture · confirmation reconciled',
    payee: '0x582a…09bf',
  },
];

export const money = (amount: number) =>
  new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(amount);

export const statusTone = (
  status: InvoiceStatus,
): 'green' | 'blue' | 'amber' | 'slate' => {
  if (status === 'Approved' || status === 'Paid') return 'green';
  if (status === 'Scheduled') return 'blue';
  if (status === 'Needs approval' || status === 'In review') return 'amber';
  return 'slate';
};
