import { useRef } from 'react';

import { useTreasury } from '@/features/treasury/api';
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
  PaymentRequest,
  RequestDetail,
  RequestInput,
  TxCall,
  TypedData,
  Vendor,
} from '@/lib/api/types';

const base = (orgId: string) => `/orgs/${orgId}/requests`;

/** Vendors with the payee usable by this treasury (a request must use its own treasury's payee). */
export const useVendors = (orgId: string, treasuryId?: string) =>
  useOrgQuery<{ items: Vendor[] }>(
    orgId,
    'payees',
    ['vendors', treasuryId],
    '/vendors',
    { query: { treasuryId } },
  );

/** The treasury's own asset (id and decimals); undefined until it has loaded. */
export const useTreasuryAsset = (
  orgId: string,
  treasuryId: string | undefined,
) => useTreasury(orgId, treasuryId).data?.treasury.asset;

/**
 * The wallet a request pays from.
 * shortcut: the treasury's first operational wallet, no picker; add one when a treasury has several.
 */
export const useTreasuryPayingWalletId = (
  orgId: string,
  treasuryId: string | undefined,
) =>
  useTreasury(orgId, treasuryId).data?.wallets.find(
    (wallet) => wallet.role === 'O1',
  )?.id;

/**
 * One Idempotency-Key per distinct submission: a retry of the same body reuses
 * it, an edited body or a success starts a new one.
 */
export function useIdempotencyKey() {
  const last = useRef<{ fingerprint: string; key: string }>();
  return {
    keyFor(fingerprint: string) {
      if (last.current?.fingerprint !== fingerprint)
        last.current = { fingerprint, key: crypto.randomUUID() };
      return last.current.key;
    },
    reset() {
      last.current = undefined;
    },
  };
}

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
    (input: {
      input: RequestInput;
      context: CreateContext;
      idempotencyKey: string;
    }) =>
      api.post<{ request: { id: string }; flags: Flag[] }>(
        base(orgId),
        toCreateBody(input.input, input.context),
        { idempotent: input.idempotencyKey },
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
    // shortcut: the API has no extraction/confirm endpoint yet (pre-existing), so this 404s;
    // replace with PATCH + terms confirm once uploads are wired to the real API.
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
      issueDate?: string | null;
      fields: Parameters<typeof toPatchBody>[0];
    }) =>
      api.patch<Versioned>(
        `${base(orgId)}/${id}`,
        toPatchBody(input.fields, input.decimals, input.issueDate),
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

/** The body the API verifies: the signed revision and message.expiry are echoed back. */
export const useApproveRequest = (orgId: string, id: string) =>
  useOrgMutation(
    orgId,
    (input: {
      signature: Hex;
      revision: number;
      expiry: number;
      idempotencyKey: string;
    }) =>
      api.post<{ request: RequestDetail }>(
        `${base(orgId)}/${id}/approve`,
        {
          signature: input.signature,
          revision: input.revision,
          expiry: input.expiry,
        },
        { idempotent: input.idempotencyKey },
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
