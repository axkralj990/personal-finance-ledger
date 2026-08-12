import type { StagedTransaction } from "../../api/types";
import {
  blockedDuplicateCount,
  defaultReviewFilter,
  effectiveCategoryId,
  effectiveSubcategoryId,
  hasSuggestedLabels,
  isActionableRow,
  matchesDescriptionSearch,
  matchesReviewFilter,
  mergeSavedRow,
  reviewCount,
  selectedInclusionChanges,
  suggestionAcceptanceChanges,
  suggestedLabels,
} from "./row-state";

const row = (patch: Partial<StagedTransaction> = {}): StagedTransaction => ({
  id: "row-1",
  rowNumber: 1,
  revision: 2,
  date: "2026-08-09",
  description: "Coffee",
  amountMinor: -500,
  currency: "SGD",
  kind: "EXPENSE",
  categoryId: null,
  subcategoryId: null,
  predictedCategoryId: null,
  predictedSubcategoryId: null,
  confidence: null,
  duplicateState: "NONE",
  duplicateExplanation: null,
  duplicateCandidate: null,
  disposition: "INCLUDE",
  ignoreReason: null,
  rememberCorrection: false,
  needsReview: false,
  errors: [],
  raw: { original: true },
  normalized: { description: "Coffee" },
  ...patch,
});

describe("review row state", () => {
  it("matches every explicit review filter", () => {
    expect(matchesReviewFilter(row({ disposition: "PENDING", needsReview: true }), "NEEDS_REVIEW")).toBe(true);
    expect(matchesReviewFilter(row({ duplicateState: "LIKELY" }), "LIKELY_DUPLICATE")).toBe(true);
    expect(matchesReviewFilter(row({ errors: ["Missing date"] }), "INVALID")).toBe(true);
    expect(matchesReviewFilter(row({ disposition: "IGNORE" }), "IGNORED")).toBe(true);
  });

  it("counts rows carrying any unresolved signal once", () => {
    expect(reviewCount([row({ needsReview: true, errors: ["Missing label"] }), row({ id: "row-2" })])).toBe(1);
  });

  it("keeps committed, audit-only, and blocked rows non-actionable", () => {
    expect(isActionableRow(row({ disposition: "COMMITTED" }))).toBe(false);
    expect(isActionableRow(row({ disposition: "AUDIT_ONLY" }))).toBe(false);
    expect(isActionableRow(row({ disposition: "BLOCKED" }))).toBe(false);
    expect(matchesReviewFilter(row({ disposition: "COMMITTED", needsReview: true }), "NEEDS_REVIEW")).toBe(false);
  });

  it("counts only actionable unresolved rows and reports blocked exact duplicates separately", () => {
    const rows = [
      row({ id: "pending", disposition: "PENDING" }),
      row({ id: "invalid", errors: ["Missing date"] }),
      row({ id: "likely", duplicateState: "LIKELY" }),
      row({ id: "blocked", disposition: "BLOCKED", duplicateState: "EXACT", needsReview: true }),
      row({ id: "committed", disposition: "COMMITTED", errors: ["Historical warning"] }),
      row({ id: "ignored", disposition: "IGNORE", errors: ["Ignored parse error"], duplicateState: "LIKELY" }),
    ];
    expect(reviewCount(rows)).toBe(3);
    expect(blockedDuplicateCount(rows)).toBe(1);
  });

  it("defaults large and partially committed batches to needs review", () => {
    expect(defaultReviewFilter([row(), row({ id: "committed", disposition: "COMMITTED" })])).toBe("NEEDS_REVIEW");
    expect(defaultReviewFilter(Array.from({ length: 101 }, (_, index) => row({ id: String(index) })))).toBe("NEEDS_REVIEW");
  });

  it("preserves source payload when a compact patch response omits it", () => {
    const merged = mergeSavedRow(row(), row({ revision: 3, categoryId: "food", raw: {}, normalized: {} }));
    expect(merged.revision).toBe(3);
    expect(merged.categoryId).toBe("food");
    expect(merged.raw).toEqual({ original: true });
  });

  it("uses predictions only while accepted labels are empty", () => {
    const suggested = row({
      disposition: "PENDING",
      predictedCategoryId: "food",
      predictedSubcategoryId: "cafes",
    });
    expect(effectiveCategoryId(suggested)).toBe("food");
    expect(effectiveSubcategoryId(suggested)).toBe("cafes");
    expect(hasSuggestedLabels(suggested)).toBe(true);
    expect(suggestedLabels(suggested)).toEqual({ categoryId: "food", subcategoryId: "cafes" });

    const edited = row({
      categoryId: "home",
      subcategoryId: null,
      predictedCategoryId: "food",
      predictedSubcategoryId: "cafes",
    });
    expect(effectiveCategoryId(edited)).toBe("home");
    expect(effectiveSubcategoryId(edited)).toBeNull();
    expect(hasSuggestedLabels(edited)).toBe(false);
  });

  it("does not offer suggestions for immutable rows", () => {
    const committed = row({
      disposition: "COMMITTED",
      predictedCategoryId: "food",
      predictedSubcategoryId: "cafes",
    });
    expect(suggestedLabels(committed)).toBeNull();
  });

  it("accepts safe suggestions atomically without resolving duplicate review", () => {
    const prediction = {
      disposition: "PENDING" as const,
      predictedCategoryId: "food",
      predictedSubcategoryId: "cafes",
    };
    expect(suggestionAcceptanceChanges(row(prediction))).toEqual({
      categoryId: "food",
      subcategoryId: "cafes",
      disposition: "INCLUDE",
    });
    expect(suggestionAcceptanceChanges(row({ ...prediction, duplicateState: "LIKELY" }))).toEqual({
      categoryId: "food",
      subcategoryId: "cafes",
    });
  });

  it("includes selected valid rows and leaves invalid rows pending", () => {
    const prediction = row({
      disposition: "PENDING",
      predictedCategoryId: "food",
      predictedSubcategoryId: "cafes",
    });
    expect(selectedInclusionChanges(prediction)).toEqual({
      categoryId: "food",
      subcategoryId: "cafes",
      disposition: "INCLUDE",
      ignoreReason: null,
    });
    expect(selectedInclusionChanges(row({ disposition: "PENDING", errors: ["Missing date"] }))).toBeNull();
    expect(selectedInclusionChanges(row({ disposition: "PENDING" }))).toBeNull();
    expect(selectedInclusionChanges(row({ disposition: "BLOCKED", categoryId: "food" }))).toBeNull();
  });

  it("searches staged descriptions case-insensitively", () => {
    const cafe = row({ description: "Synthetic Cafe Ljubljana" });
    expect(matchesDescriptionSearch(cafe, "cafe")).toBe(true);
    expect(matchesDescriptionSearch(cafe, " LJUBLJANA ")).toBe(true);
    expect(matchesDescriptionSearch(cafe, "market")).toBe(false);
    expect(matchesDescriptionSearch(cafe, "")).toBe(true);
  });
});
