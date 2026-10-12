import { useOrgMutation, useOrgQuery } from '@/lib/api/hooks';
import { api } from '@/lib/api/http';
import type {
  CsvImportResult,
  Flag,
  Hex,
  PaymentOption,
  PaymentRequest,
  RequestDetail,
  RequestInput,
  TxCall,
  TypedData,
  Vendor,
} from '@/lib/api/types';

const base = (orgId: string) => `/orgs/${orgId}/requests`;

export const useVendors = (orgId: string) =>
  useOrgQuery<{ items: Vendor[] }>(orgId, 'payees', ['vendors'], '/vendors');

export const useRequests = (orgId: string, status?: string) =>
  useOrgQuery<{ items: PaymentRequest[] }>(
    orgId,
    'requests',
    ['list'],
    '/requests',
    { query: { status } },
  );

export const useRequest = (orgId: string, id: string | undefined) =>
  useOrgQuery<RequestDetail>(
    orgId,
    'requests',
    ['detail', id],
    `/requests/${id}`,
    {
      enabled: Boolean(id),
    },
  );

export const useCreateRequest = (orgId: string) =>
  useOrgMutation(orgId, (input: RequestInput) =>
    api.post<{ request: PaymentRequest; flags: Flag[] }>(base(orgId), input, {
      idempotent: true,
    }),
  );

export const useUploadInvoice = (orgId: string) =>
  useOrgMutation(orgId, (input: { file: File; treasuryId: string }) => {
    const form = new FormData();
    form.set('file', input.file);
    form.set('treasuryId', input.treasuryId);
    return api.upload<{ requestId: string }>(`${base(orgId)}/upload`, form);
  });

export const useImportCsv = (orgId: string) =>
  useOrgMutation(orgId, (file: File) => {
    const form = new FormData();
    form.set('file', file);
    return api.upload<CsvImportResult>(`${base(orgId)}/import-csv`, form);
  });

export const useConfirmExtraction = (orgId: string, id: string) =>
  useOrgMutation(orgId, (fields: Record<string, string>) =>
    api.post<{ request: RequestDetail }>(
      `${base(orgId)}/${id}/extraction/confirm`,
      { fields },
    ),
  );

export const useConfirmTerms = (orgId: string, id: string) =>
  useOrgMutation(
    orgId,
    (terms: { earlyPayDate?: string; earlyDiscountBps?: number }) =>
      api.post<{ request: RequestDetail }>(
        `${base(orgId)}/${id}/terms/confirm`,
        { terms },
      ),
  );

export const useEditRequest = (orgId: string, id: string) =>
  useOrgMutation(
    orgId,
    (input: { version: string; fields: Partial<RequestInput> }) =>
      api.patch<{ request: RequestDetail }>(
        `${base(orgId)}/${id}`,
        input.fields,
        { ifMatch: input.version },
      ),
  );

type Transition =
  | 'submit'
  | 'withdraw'
  | 'reject'
  | 'request-changes'
  | 'cancel';

export const useRequestTransition = (orgId: string, id: string) =>
  useOrgMutation(orgId, (input: { action: Transition; reason?: string }) =>
    api.post<{ request: RequestDetail }>(
      `${base(orgId)}/${id}/${input.action}`,
      input.reason !== undefined ? { reason: input.reason } : undefined,
    ),
  );

export const useAcknowledgeFlag = (orgId: string, id: string) =>
  useOrgMutation(orgId, (input: { flagId: string; note: string }) =>
    api.post<{ flag: Flag }>(`${base(orgId)}/${id}/flags/${input.flagId}/ack`, {
      note: input.note,
    }),
  );

export const useApprovalTypedData = (
  orgId: string,
  id: string,
  enabled: boolean,
) =>
  useOrgQuery<TypedData>(
    orgId,
    'requests',
    ['typed-data', id],
    `/requests/${id}/approval-typed-data`,
    { enabled, staleTime: 0 },
  );

export const useApproveRequest = (orgId: string, id: string) =>
  useOrgMutation(
    orgId,
    (input: { signature: Hex; option: PaymentOption['kind'] }) =>
      api.post<{ request: RequestDetail }>(
        `${base(orgId)}/${id}/approve`,
        input,
        { idempotent: true },
      ),
  );

export const fetchCancelTx = (orgId: string, id: string) =>
  api.get<TxCall>(`${base(orgId)}/${id}/cancel-tx`);

export const useReportCancelTx = (orgId: string, id: string) =>
  useOrgMutation(orgId, (txHash: Hex) =>
    api.post<{ cancelOnchain: string }>(
      `${base(orgId)}/${id}/cancel-tx/submitted`,
      { txHash },
    ),
  );

export const fetchEvidence = (orgId: string, id: string) =>
  api.get<Record<string, unknown>>(`${base(orgId)}/${id}/evidence`);
