import { Navigate, Route, Routes } from 'react-router-dom';

import { AuthGuard } from '@/features/auth/auth-guard';
import { LoginPage } from '@/routes/login-page';
import { MockDashboardPage } from '@/routes/mock/mock-dashboard-page';
import { MockInvoicesPage } from '@/routes/mock/mock-invoices-page';
import { MockPaymentPlanPage } from '@/routes/mock/mock-payment-plan-page';
import { MockTreasuryPage } from '@/routes/mock/mock-treasury-page';

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AuthGuard />}>
        <Route index element={<Navigate to="/mock" replace />} />
        <Route path="/mock" element={<MockDashboardPage />} />
        <Route path="/mock/invoices" element={<MockInvoicesPage />} />
        <Route path="/mock/plans" element={<MockPaymentPlanPage />} />
        <Route path="/mock/treasury" element={<MockTreasuryPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
