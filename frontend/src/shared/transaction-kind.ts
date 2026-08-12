export function transactionKindError(amountMinor: number): string | null {
  if (amountMinor === 0) return "Amount cannot be zero.";
  return null;
}
