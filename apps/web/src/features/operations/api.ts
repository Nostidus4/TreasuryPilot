import { useOrgMutation, useOrgQuery } from '@/lib/api/hooks';
import { api, apiUrl } from '@/lib/api/http';
import type {
  CopilotMessage,
  ExceptionDetail,
  GovernanceTx,
  Notification,
  OperationsMetrics,
  Plan,
  PlanDetail,
  Reconciliation,
  ReviewItem,
  SavingsMetrics,
} from '@/lib/api/types';

/* ───────────── Plans ───────────── */

export const usePlans = (orgId: string, treasuryId: string) =>
  useOrgQuery<{ items: Plan[] }>(
    orgId,
    'plans',
    ['list', treasuryId],
    `/treasuries/${treasuryId}/plans`,
  );

export const usePlan = (orgId: string, planId: string, live = true) =>
  useOrgQuery<PlanDetail>(
    orgId,
    'plans',
    ['detail', planId],
    `/plans/${planId}`,
    {
      // The org-wide stream normally refreshes this query immediately. Keep
      // the active timeline within WEB-012's two-second target whenever SSE is
      // not connected (initial connect, drop, or no EventSource support).
      refetchInterval: live ? false : 2_000,
    },
  );

export const useRunNow = (orgId: string, treasuryId: string) =>
  useOrgMutation(orgId, () =>
    api.post<{ jobId: string; planId: string }>(
      `/orgs/${orgId}/treasuries/${treasuryId}/run-now`,
      undefined,
      { idempotent: true },
    ),
  );

/* ───────────── Review & exceptions ───────────── */

export const useReviewItems = (orgId: string) =>
  useOrgQuery<{ items: ReviewItem[] }>(
    orgId,
    'review',
    ['list'],
    '/review-items',
  );

export const useReviewAction = (orgId: string) =>
  useOrgMutation(orgId, (input: { id: string; action: string; note: string }) =>
    api.post<{ item: ReviewItem }>(
      `/orgs/${orgId}/review-items/${input.id}/actions`,
      { action: input.action, note: input.note },
      { idempotent: true },
    ),
  );

export const useException = (orgId: string, requestId: string | undefined) =>
  useOrgQuery<ExceptionDetail>(
    orgId,
    'review',
    ['exception', requestId],
    `/requests/${requestId}/exception`,
    { enabled: Boolean(requestId) },
  );

export const useGrantExceptionTx = (orgId: string) =>
  useOrgMutation(orgId, (input: { requestId: string; expiryHours: number }) =>
    api.post<{ governanceTx: GovernanceTx }>(
      `/orgs/${orgId}/requests/${input.requestId}/exception/grant-tx`,
      { expiryHours: input.expiryHours },
    ),
  );

export const useRejectException = (orgId: string) =>
  useOrgMutation(orgId, (input: { requestId: string; reason: string }) =>
    api.post<unknown>(
      `/orgs/${orgId}/requests/${input.requestId}/exception/reject`,
      { reason: input.reason },
    ),
  );

/* ───────────── Reconciliation ───────────── */

export const useReconciliations = (orgId: string) =>
  useOrgQuery<{ items: Reconciliation[] }>(
    orgId,
    'reconciliations',
    ['list'],
    '/reconciliations',
  );

export const useReconcile = (orgId: string) =>
  useOrgMutation(
    orgId,
    (input: { id: string; outcome: 'match' | 'discrepancy'; note: string }) =>
      api.post<{ reconciliation: Reconciliation }>(
        `/orgs/${orgId}/reconciliations/${input.id}/${input.outcome}`,
        { note: input.note },
      ),
  );

export const reconciliationExportUrl = (orgId: string) =>
  apiUrl(`/orgs/${orgId}/exports/reconciliation.csv`, { format: 'csv' });

/* ───────────── Metrics ───────────── */

export const useOperationsMetrics = (orgId: string) =>
  useOrgQuery<{ metrics: OperationsMetrics }>(
    orgId,
    'metrics',
    ['operations'],
    '/metrics/operations',
  );

export const useSavingsMetrics = (orgId: string) =>
  useOrgQuery<SavingsMetrics>(
    orgId,
    'metrics',
    ['savings'],
    '/metrics/savings',
  );

/* ───────────── Notifications ───────────── */

export const useNotifications = (orgId: string) =>
  useOrgQuery<{ items: Notification[] }>(
    orgId,
    'notifications',
    [],
    '/notifications',
  );

export const useMarkNotificationRead = (orgId: string) =>
  useOrgMutation(orgId, (id: string) =>
    api.post<void>(`/orgs/${orgId}/notifications/${id}/read`),
  );

/* ───────────── Copilot ───────────── */

export const createCopilotThread = (orgId: string) =>
  api.post<{ threadId: string }>(`/orgs/${orgId}/copilot/threads`);

export const askCopilot = (
  orgId: string,
  threadId: string,
  input: { text: string; treasuryId?: string },
) =>
  api.post<{ message: CopilotMessage }>(
    `/orgs/${orgId}/copilot/threads/${threadId}/messages`,
    input,
  );
