import type { RequestInput } from '@/lib/api/types';
import { formatUnits } from '@/lib/money';

/** What the API needs beyond the form: ids resolved from vendor and treasury data. */
export interface CreateContext {
  assetId: string;
  decimals: number;
  payeeId: string;
}

const day = (iso: string) => iso.slice(0, 10);
// 86_400_000 ms per day: the API counts days since 1970-01-01 UTC.
const epochDay = (iso: string) => Math.floor(Date.parse(day(iso)) / 86_400_000);
const today = () => new Date().toISOString().slice(0, 10);

/** The API's terms use days since the Unix epoch, not dates. */
export function toApiTerms(terms: {
  dueDate: string;
  earlyPayDate?: string;
  earlyDiscountBps?: number;
}) {
  return {
    netDueDay: epochDay(terms.dueDate),
    ...(terms.earlyPayDate && terms.earlyDiscountBps
      ? {
          discountBps: terms.earlyDiscountBps,
          discountDeadlineDay: epochDay(terms.earlyPayDate),
        }
      : {}),
  };
}

/** `POST /requests` body: base units become a decimal string, `description` is `note`. */
export function toCreateBody(input: RequestInput, ctx: CreateContext) {
  const dueDate = day(input.dueDate);
  return {
    treasuryId: input.treasuryId,
    vendorId: input.vendorId,
    payeeId: ctx.payeeId,
    assetId: ctx.assetId,
    invoiceNo: input.invoiceNumber,
    issueDate: today() < dueDate ? today() : dueDate,
    dueDate,
    amount: formatUnits(input.amount, ctx.decimals, { group: false }),
    note: input.description,
    terms: toApiTerms(input),
  };
}

/** `PATCH /requests/{id}` body for the editable form fields. */
export function toPatchBody(
  fields: Pick<
    RequestInput,
    'invoiceNumber' | 'amount' | 'dueDate' | 'description'
  >,
  decimals: number,
  issueDate?: string | null,
) {
  const dueDate = day(fields.dueDate);
  return {
    // The API requires issueDate <= dueDate; pull it back when the due date moves before it.
    ...(issueDate && dueDate < day(issueDate) ? { issueDate: dueDate } : {}),
    invoiceNo: fields.invoiceNumber,
    amount: formatUnits(fields.amount, decimals, { group: false }),
    dueDate,
    note: fields.description,
  };
}
