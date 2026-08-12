import type { DashboardMonthlyCompositionItem, DashboardRankedCompositionItem } from "../../api/types";
import { buildCompositionChartData, ledgerColorForId, OTHER_TAXONOMY_ID } from "./composition";

describe("dashboard composition transforms", () => {
  it("keeps the top taxonomy IDs and combines the remainder without losing monthly totals", () => {
    const ranked: DashboardRankedCompositionItem[] = [
      { taxonomyId: "b", name: "B", amountMinor: 500, count: 1, percentage: 50 },
      { taxonomyId: "a", name: "A", amountMinor: 300, count: 1, percentage: 30 },
      { taxonomyId: "c", name: "C", amountMinor: 200, count: 1, percentage: 20 },
    ];
    const monthly: DashboardMonthlyCompositionItem[] = ranked.map((item) => ({
      period: "2026-01", taxonomyId: item.taxonomyId, name: item.name, amountMinor: item.amountMinor, count: item.count, partial: false,
    }));

    const result = buildCompositionChartData(monthly, ranked, 2);

    expect(result.columns.map((column) => column.taxonomyId)).toEqual(["b", "a", OTHER_TAXONOMY_ID]);
    expect(new Set(result.columns.map((column) => column.color)).size).toBe(result.columns.length);
    expect(result.rows[0]).toMatchObject({ taxonomy0: 500, taxonomy1: 300, taxonomy2: 200 });
    const plottedTotal = result.columns.reduce((total, column) => total + Number(result.rows[0]?.[column.key]), 0);
    expect(plottedTotal).toBe(1000);
  });

  it("assigns stable deterministic colors from the fixed ledger palette", () => {
    expect(ledgerColorForId("food")).toBe(ledgerColorForId("food"));
    expect(ledgerColorForId("food")).toMatch(/^#[0-9a-f]{6}$/i);
    expect(ledgerColorForId(OTHER_TAXONOMY_ID)).toBe("#8a887f");
  });

  it("retains zero-spend and partial months from the selected calendar range", () => {
    const result = buildCompositionChartData(
      [{ period: "2026-01", taxonomyId: "food", name: "Food", amountMinor: 500, count: 1, partial: false }],
      [{ taxonomyId: "food", name: "Food", amountMinor: 500, count: 1, percentage: 100 }],
      8,
      [
        { label: "2026-01", partial: false },
        { label: "2026-02", partial: true },
      ],
    );

    expect(result.rows).toHaveLength(2);
    expect(result.rows[1]).toMatchObject({ period: "2026-02", partial: true, taxonomy0: 0 });
  });
});
