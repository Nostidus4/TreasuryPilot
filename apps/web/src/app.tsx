import { lazy, Suspense, type ComponentType } from 'react';
import { Navigate, Outlet, Route, Routes } from 'react-router-dom';

import { Skeleton } from '@/components/ui/misc';

import {
  AuthGuard,
  HomeRedirect,
  LoginPage,
  VerifyPage,
} from '@/features/auth/auth-pages';
import { OrgLayout } from '@/features/orgs/org-scope';
import {
  OnboardingPage,
  OrgIndexRedirect,
  OrgsPage,
} from '@/features/orgs/orgs-pages';

/** Each screen is its own chunk; the shell stays in the entry bundle. */
function page<
  Module extends Record<string, unknown>,
  Name extends keyof Module,
>(load: () => Promise<Module>, name: Name) {
  return lazy(async () => ({
    default: (await load())[name] as ComponentType,
  }));
}

const ApprovalsPage = page(
  () => import('@/features/approvals/approvals-page'),
  'ApprovalsPage',
);
const GovernancePage = page(
  () => import('@/features/governance/governance-page'),
  'GovernancePage',
);
const MandatePage = page(
  () => import('@/features/mandate/mandate-page'),
  'MandatePage',
);
const MembersPage = page(
  () => import('@/features/members/members-page'),
  'MembersPage',
);
const MetricsPage = page(
  () => import('@/features/metrics/metrics-page'),
  'MetricsPage',
);
const PayeesPage = page(
  () => import('@/features/payees/payees-page'),
  'PayeesPage',
);
const PlanDetailPage = page(
  () => import('@/features/plans/plans-pages'),
  'PlanDetailPage',
);
const PlansPage = page(
  () => import('@/features/plans/plans-pages'),
  'PlansPage',
);
const ReconciliationPage = page(
  () => import('@/features/reconciliation/reconciliation-page'),
  'ReconciliationPage',
);
const ImportCsvPage = page(
  () => import('@/features/requests/intake-pages'),
  'ImportCsvPage',
);
const NewRequestPage = page(
  () => import('@/features/requests/intake-pages'),
  'NewRequestPage',
);
const UploadInvoicePage = page(
  () => import('@/features/requests/intake-pages'),
  'UploadInvoicePage',
);
const RequestDetailPage = page(
  () => import('@/features/requests/request-detail-page'),
  'RequestDetailPage',
);
const RequestsPage = page(
  () => import('@/features/requests/requests-page'),
  'RequestsPage',
);
const ReviewPage = page(
  () => import('@/features/review/review-page'),
  'ReviewPage',
);
const DashboardPage = page(
  () => import('@/features/treasury/dashboard-page'),
  'DashboardPage',
);
const BorrowProposalPage = page(
  () => import('@/features/treasury/fees-borrow-pages'),
  'BorrowProposalPage',
);
const FeesPage = page(
  () => import('@/features/treasury/fees-borrow-pages'),
  'FeesPage',
);
const SetupWizardPage = page(
  () => import('@/features/treasury/setup-wizard-page'),
  'SetupWizardPage',
);
const WalletsPage = page(
  () => import('@/features/auth/wallets-page'),
  'WalletsPage',
);

function PageFallback() {
  return (
    <div
      className="mx-auto grid w-full max-w-6xl gap-4 px-4 py-6 sm:px-6 lg:px-8"
      aria-busy="true"
    >
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

/** Route map: docs/modules/web §3. */
export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/verify" element={<VerifyPage />} />
      <Route element={<AuthGuard />}>
        <Route
          element={
            <Suspense fallback={<PageFallback />}>
              <Outlet />
            </Suspense>
          }
        >
          <Route index element={<HomeRedirect />} />
          <Route path="/orgs" element={<OrgsPage />} />
          <Route path="/me/wallets" element={<WalletsPage />} />
          <Route path="/o/:org" element={<OrgLayout />}>
            <Route index element={<OrgIndexRedirect />} />
            <Route path="onboarding" element={<OnboardingPage />} />
            <Route path="t/:t" element={<DashboardPage />} />
            <Route path="treasuries/new" element={<SetupWizardPage />} />
            <Route path="t/:t/mandate" element={<MandatePage />} />
            <Route path="t/:t/payees" element={<PayeesPage />} />
            <Route path="t/:t/settings/fees" element={<FeesPage />} />
            <Route path="t/:t/borrow/:id" element={<BorrowProposalPage />} />
            <Route path="review" element={<ReviewPage />} />
            <Route path="reconciliation" element={<ReconciliationPage />} />
            <Route path="members" element={<MembersPage />} />
            <Route path="metrics" element={<MetricsPage />} />
            <Route path="t/:t/plans" element={<PlansPage />} />
            <Route path="t/:t/plans/:p" element={<PlanDetailPage />} />
            <Route path="requests" element={<RequestsPage />} />
            <Route path="requests/new" element={<NewRequestPage />} />
            <Route path="requests/upload" element={<UploadInvoicePage />} />
            <Route path="requests/import" element={<ImportCsvPage />} />
            <Route path="requests/:r" element={<RequestDetailPage />} />
            <Route path="approvals" element={<ApprovalsPage />} />
            <Route path="approvals/:r" element={<ApprovalsPage />} />
            <Route path="governance" element={<GovernancePage />} />
            <Route path="governance/:g" element={<GovernancePage />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
