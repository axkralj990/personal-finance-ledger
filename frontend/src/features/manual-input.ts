import type { ManualTransactionInput } from "../api/types";
import { parseMajorAmount } from "../shared/format";
import { transactionKindError } from "../shared/transaction-kind";

export interface ManualRow {
  id: string;
  accountId: string;
  date: string;
  description: string;
  amount: string;
  currency: string;
  categoryId: string;
  subcategoryId: string;
}

export function manualRowError(row: ManualRow): string | null {
  const amountMinor = parseMajorAmount(row.amount);
  if (!row.accountId || !row.date || !row.description.trim() || !row.currency || amountMinor === null) {
    return "Complete account, date, description, amount, and currency with at most two decimal places.";
  }
  return transactionKindError(amountMinor);
}

export function toManualInput(row: ManualRow): ManualTransactionInput | null {
  const amountMinor = parseMajorAmount(row.amount);
  if (manualRowError(row) || amountMinor === null) return null;
  return {
    accountId: row.accountId,
    date: row.date,
    description: row.description.trim(),
    amountMinor,
    currency: row.currency.toUpperCase(),
    categoryId: row.categoryId || null,
    subcategoryId: row.subcategoryId || null,
  };
}
