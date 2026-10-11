import { Navigate, Route, Routes } from 'react-router-dom';

import { AppLayout } from '@/components/app-layout';
import { EmptyState } from '@/components/empty-state';
import { AuthGuard } from '@/features/auth/auth-guard';
import { LoginPage } from '@/routes/login-page';

function DashboardShell() {
  return (
    <EmptyState
      eyebrow="Workspace ready"
      title="Treasury dashboard"
      description="Balances, mandates and payment activity will appear here as their module tickets land."
    />
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AuthGuard />}>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardShell />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
