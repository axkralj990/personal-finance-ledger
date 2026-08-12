import type { Asset, PortfolioHolding } from "../../api/types";
import { allocationByGroup, groupHoldings, pnlByGroup } from "./grouping";

function asset(id: string, quantity: string, exchange = "LSEETF"): Asset {
  return {
    id,
    name: "ERNA",
    assetType: "ETF",
    currency: "USD",
    acquisitionDate: "2026-01-13",
    quantity,
    costBasisNativeMinor: 10000,
    costBasisEurMinor: 9000,
    costBasisFxSource: "ECB",
    costBasisFxRateToEur: "0.9",
    costBasisFxRateDate: "2026-01-13",
    quote: { symbol: "ERNA", exchange, micCode: null },
    isActive: true,
    revision: 1,
    createdAt: "2026-01-13T00:00:00Z",
    updatedAt: "2026-01-13T00:00:00Z",
    archivedAt: null,
    archivedOn: null,
    latestValuation: null,
  };
}

function holding(id: string, quantity: string, valued: boolean): PortfolioHolding {
  return {
    assetId: id,
    name: "ERNA",
    assetType: "ETF",
    currency: "USD",
    revision: 1,
    quantity,
    valuationId: valued ? `valuation-${id}` : null,
    valuedAt: valued ? "2026-08-11" : null,
    source: valued ? "TWELVE_DATA" : null,
    nativeValueMinor: valued ? 12000 : null,
    eurValueMinor: valued ? 10000 : null,
    costBasisEurMinor: valued ? 9000 : null,
    unrealizedPnlMinor: valued ? 1000 : null,
    returnPercent: valued ? "11.111111" : null,
    missingValuation: !valued,
  };
}

describe("portfolio holding grouping", () => {
  it("sums decimal quantities exactly and preserves partial coverage", () => {
    const assets = [asset("lot-1", "0.8342"), asset("lot-2", "1073")];
    const groups = groupHoldings(
      [holding("lot-1", "0.8342", true), holding("lot-2", "1073", false)],
      assets,
    );

    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({
      name: "ERNA",
      quantity: "1073.8342",
      eurValueMinor: 10000,
      valuedCount: 1,
      pnlCoveredCount: 1,
      missingValuation: true,
    });
    expect(allocationByGroup(groups, 10000)).toEqual([
      expect.objectContaining({ name: "ERNA", valueMinor: 10000, percentage: "100" }),
    ]);
    expect(pnlByGroup(groups)).toEqual([
      expect.objectContaining({ name: "ERNA", costBasisEurMinor: 9000, currentValueEurMinor: 10000, unrealizedPnlMinor: 1000 }),
    ]);
  });

  it("keeps the same ticker on different exchanges separate", () => {
    const assets = [asset("lse-lot", "1"), asset("aeb-lot", "2", "AEB")];
    const groups = groupHoldings(
      [holding("lse-lot", "1", true), holding("aeb-lot", "2", true)],
      assets,
    );

    expect(groups).toHaveLength(2);
    expect(groups.map((group) => group.exchange)).toEqual(["LSEETF", "AEB"]);
    expect(allocationByGroup(groups, 20000).map((item) => item.name)).toEqual([
      "ERNA (AEB)",
      "ERNA (LSEETF)",
    ]);
  });

  it("keeps the original position name when a newer lot is backdated", () => {
    const originalAsset = { ...asset("original", "1"), name: "Short Duration Fund", acquisitionDate: "2026-01-13", createdAt: "2026-01-13T00:00:00Z" };
    const newBackdatedAsset = { ...asset("new-lot", "2"), acquisitionDate: "2025-01-13", createdAt: "2026-08-11T00:00:00Z" };
    const originalHolding = { ...holding("original", "1", true), name: "Short Duration Fund" };

    const groups = groupHoldings(
      [holding("new-lot", "2", true), originalHolding],
      [newBackdatedAsset, originalAsset],
    );

    expect(groups[0]?.name).toBe("Short Duration Fund");
  });
});
