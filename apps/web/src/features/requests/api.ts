import { useOrgMutation, useOrgQuery } from '@/lib/api/hooks';
import { api } from '@/lib/api/http';
import {
  toApiTerms,
  toCreateBody,
  toPatchBody,
  type CreateContext,
} from '@/features/requests/wire';
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
  useOrgMutation(
    orgId,
    (input: { input: RequestInput; context: CreateContext }) =>
      api.post<{ request: { id: string }; flags: Flag[] }>(
        base(orgId),
        toCreateBody(input.input, input.context),
        { idempotent: true },
      ),
  );

export const useUploadInvoice = (orgId: string) =>
  useOrgMutation(orgId, (input: { file: File; treasuryId: string }) => {
    const form = new FormData();
    form.set('file', input.file);
    form.set('treasuryId', input.treasuryId);
    return api.upload<{ requestId: string }>(`${base(orgId)}/upload`, form);
  });

export const useImportCsv = (orgId: string) =>
  useOrgMutation(orgId, (input: { file: File; treasuryId: string }) => {
    const form = new FormData();
    form.set('file', input.file);
    form.set('treasuryId', input.treasuryId);
    return api.upload<CsvImportResult>(`${base(orgId)}/import-csv`, form);
  });

export const useConfirmExtraction = (orgId: string, id: string) =>
  useOrgMutation(orgId, (fields: Record<string, string>) =>
    api.post<{ request: RequestDetail }>(
      `${base(orgId)}/${id}/extraction/confirm`,
      { fields },
    ),
  );

/** Edits, term confirmation and transitions answer with the new `request.version`. */
type Versioned = { request: { version: number | string } };

export const useConfirmTerms = (orgId: string, id: string) =>
  useOrgMutation(
    orgId,
    (input: {
      version: string;
      dueDate: string;
      earlyPayDate?: string;
      earlyDiscountBps?: number;
    }) =>
      api.post<Versioned>(
        `${base(orgId)}/${id}/terms/confirm`,
        { terms: toApiTerms(input) },
        { ifMatch: input.version },
      ),
  );

export const useEditRequest = (orgId: string, id: string) =>
  useOrgMutation(
    orgId,
    (input: {
      version: string;
      decimals: number;
      fields: Parameters<typeof toPatchBody>[0];
    }) =>
      api.patch<Versioned>(
        `${base(orgId)}/${id}`,
        toPatchBody(input.fields, input.decimals),
        { ifMatch: input.version },
      ),
  );

type Transition =
  | 'submit'
  | 'withdraw'
  | 'reject'
  | 'request-changes'
  | 'cancel';

export const useRequestTransition = (
  orgId: string,
  id: string,
  version: string,
) =>
  useOrgMutation(
    orgId,
    (input: { action: Transition; reason?: string; version?: string }) =>
      api.post<Versioned>(
        `${base(orgId)}/${id}/${input.action}`,
        input.reason !== undefined ? { reason: input.reason } : undefined,
        { ifMatch: input.version ?? version },
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
