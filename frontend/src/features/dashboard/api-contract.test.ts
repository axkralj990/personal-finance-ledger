import { ApiClient } from "../../api/client";
import { mapDashboard } from "../../api/mappers";
import { dashboardResponse } from "./test-fixture";

describe("dashboard API contract", () => {
  it("maps realistic snake_case dashboard JSON to typed camelCase data", () => {
    const dashboard = mapDashboard(dashboardResponse);

    expect(dashboard.meta).toMatchObject({ dateFrom: "2025-08-10", dataTo: "2026-08-09", currency: "EUR" });
    expect(dashboard.meta.partialPeriods.month).toEqual({ first: true, last: true });
    expect(dashboard.summary.monthlySpendingMean).toMatchObject({ currentMinor: 58879, deltaPercent: null });
    expect(dashboard.series.month[0]).toMatchObject({ incomeTotalMinor: 100000, selectedDays: 22 });
    expect(dashboard.series.rollingMean.month[0]).toMatchObject({ incomeMeanMinor: 100000, windowMonths: 1 });
    expect(dashboard.composition.spending.categoryRanked[0]).toMatchObject({ taxonomyId: "food", amountMinor: 110000 });
    expect(dashboard.composition.income.subcategoryRanked[0]).toMatchObject({ taxonomyId: "salary", amountMinor: 220000 });
    expect(dashboard.annual[0]?.months).toHaveLength(12);
    expect(dashboard.recent[0]).toMatchObject({ accountName: "Main EUR", kind: "EXPENSE" });
    expect(dashboard.quality.categoryOnlyCount).toBe(2);
  });

  it("sends date filters and repeated taxonomy query parameters", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      void input;
      return new Response(JSON.stringify(dashboardResponse), {
      status: 200,
      headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await new ApiClient().dashboard.get({
      dateFrom: "2025-08-10",
      dateTo: "2026-08-10",
      categoryIds: ["food", "travel"],
      subcategoryIds: ["cafes", "flights"],
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/dashboard?date_from=2025-08-10&date_to=2026-08-10&category_id=food&category_id=travel&subcategory_id=cafes&subcategory_id=flights");
  });
});
