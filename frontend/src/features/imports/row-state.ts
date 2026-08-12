import type { StagedTransaction } from "../../api/types";

export type ReviewFilter = "ALL" | "NEEDS_REVIEW" | "LIKELY_DUPLICATE" | "INVALID" | "IGNORED";
export type SaveState = "IDLE" | "SAVING" | "SAVED" | "CONFLICT" | "ERROR";

const editableDispositions = new Set(["PENDING", "INCLUDE", "IGNORE"]);

export function isActionableRow(row: StagedTransaction): boolean {
  return editableDispositions.has(row.disposition);
}

export function isUnresolvedRow(row: StagedTransaction): boolean {
  return isActionableRow(row) && row.disposition !== "IGNORE" && (row.disposition === "PENDING" || row.errors.length > 0 || row.duplicateState === "LIKELY");
}

export function defaultReviewFilter(rows: StagedTransaction[]): ReviewFilter {
  return rows.length > 100 || rows.some((row) => !isActionableRow(row)) ? "NEEDS_REVIEW" : "ALL";
}

export function matchesReviewFilter(row: StagedTransaction, filter: ReviewFilter): boolean {
  switch (filter) {
    case "NEEDS_REVIEW":
      return isUnresolvedRow(row);
    case "LIKELY_DUPLICATE":
      return isActionableRow(row) && row.disposition !== "IGNORE" && row.duplicateState === "LIKELY";
    case "INVALID":
      return isActionableRow(row) && row.disposition !== "IGNORE" && row.errors.length > 0;
    case "IGNORED":
      return isActionableRow(row) && row.disposition === "IGNORE";
    default:
      return true;
  }
}

export function matchesDescriptionSearch(row: StagedTransaction, search: string): boolean {
  const normalized = search.trim().toLocaleLowerCase();
  return !normalized || Boolean(row.description?.toLocaleLowerCase().includes(normalized));
}

export function reviewCount(rows: StagedTransaction[]): number {
  return rows.filter(isUnresolvedRow).length;
}

export function blockedDuplicateCount(rows: StagedTransaction[]): number {
  return rows.filter((row) => row.disposition === "BLOCKED" && row.duplicateState === "EXACT").length;
}

export function effectiveCategoryId(row: StagedTransaction): string | null {
  return row.categoryId ?? row.predictedCategoryId;
}

export function effectiveSubcategoryId(row: StagedTransaction): string | null {
  if (row.categoryId !== null) return row.subcategoryId;
  return row.predictedCategoryId ? row.predictedSubcategoryId : null;
}

export function hasSuggestedLabels(row: StagedTransaction): boolean {
  return row.categoryId === null && row.predictedCategoryId !== null;
}

export function suggestedLabels(
  row: StagedTransaction,
): { categoryId: string; subcategoryId: string | null } | null {
  if (!isActionableRow(row) || !hasSuggestedLabels(row)) return null;
  return {
    categoryId: row.predictedCategoryId!,
    subcategoryId: row.predictedSubcategoryId,
  };
}

export function suggestionAcceptanceChanges(row: StagedTransaction): {
  categoryId: string;
  subcategoryId: string | null;
  disposition?: "INCLUDE";
} | null {
  const labels = suggestedLabels(row);
  if (!labels) return null;
  const canResolve = row.errors.length === 0 && row.duplicateState === "NONE";
  return {
    ...labels,
    ...(canResolve && { disposition: "INCLUDE" as const }),
  };
}

export function selectedInclusionChanges(row: StagedTransaction): {
  categoryId?: string;
  subcategoryId?: string | null;
  disposition: "INCLUDE";
  ignoreReason: null;
} | null {
  if (
    !isActionableRow(row)
    || row.errors.length > 0
    || !(row.categoryId ?? row.predictedCategoryId)
  ) {
    return null;
  }
  return {
    ...(suggestedLabels(row) ?? {}),
    disposition: "INCLUDE",
    ignoreReason: null,
  };
}

export function mergeSavedRow(current: StagedTransaction, saved: StagedTransaction): StagedTransaction {
  return {
    ...current,
    ...saved,
    raw: Object.keys(saved.raw).length ? saved.raw : current.raw,
    normalized: Object.keys(saved.normalized).length ? saved.normalized : current.normalized,
    revision: saved.revision || current.revision + 1,
  };
}
