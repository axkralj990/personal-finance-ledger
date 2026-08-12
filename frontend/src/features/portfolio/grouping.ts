import type { AllocationItem, Asset, AssetPnl, PortfolioHolding, ValuationSource } from "../../api/types";

const SECURITY_TYPES = new Set(["ETF", "STOCK"]);

export interface PortfolioLot {
  asset: Asset | undefined;
  holding: PortfolioHolding;
}

export interface HoldingGroup {
  key: string;
  name: string;
  assetType: PortfolioHolding["assetType"];
  currency: string;
  symbol: string | null;
  exchange: string | null;
  micCode: string | null;
  lots: PortfolioLot[];
  quantity: string | null;
  nativeValueMinor: number | null;
  eurValueMinor: number | null;
  costBasisEurMinor: number | null;
  unrealizedPnlMinor: number | null;
  returnPercent: string | null;
  valuedAt: string | null;
  source: ValuationSource | null;
  mixedEvidence: boolean;
  valuedCount: number;
  costCoveredCount: number;
  pnlCoveredCount: number;
  missingValuation: boolean;
  isSecurity: boolean;
}

export function groupHoldings(holdings: PortfolioHolding[], assets: Asset[]): HoldingGroup[] {
  const assetById = new Map(assets.map((asset) => [asset.id, asset]));
  const grouped = new Map<string, PortfolioLot[]>();
  for (const holding of holdings) {
    const asset = assetById.get(holding.assetId);
    const key = groupKey(holding, asset);
    grouped.set(key, [...(grouped.get(key) ?? []), { asset, holding }]);
  }
  return [...grouped.entries()].map(([key, lots]) => aggregateGroup(key, lots));
}

export function assetPositionKey(asset: Asset): string {
  if (!SECURITY_TYPES.has(asset.assetType) || !asset.quote) return `asset:${asset.id}`;
  const venue = asset.quote.exchange ?? asset.quote.micCode ?? "";
  return `security:${asset.assetType}:${asset.currency}:${asset.quote.symbol}:${venue}`;
}

export function allocationByGroup(
  groups: HoldingGroup[],
  knownValueMinor: number,
): AllocationItem[] {
  const labels = chartLabels(groups);
  return groups
    .filter((group) => group.eurValueMinor !== null)
    .map((group) => ({
      key: group.key,
      name: labels.get(group.key) ?? group.name,
      valueMinor: group.eurValueMinor ?? 0,
      percentage: percentage(group.eurValueMinor ?? 0, knownValueMinor),
    }))
    .sort((left, right) => right.valueMinor - left.valueMinor || left.name.localeCompare(right.name));
}

export function pnlByGroup(groups: HoldingGroup[]): AssetPnl[] {
  const labels = chartLabels(groups);
  return groups
    .filter((group) => group.assetType !== "BANK_CASH" && group.assetType !== "BROKERAGE_CASH")
    .map((group) => ({
      assetId: group.key,
      name: labels.get(group.key) ?? group.name,
      costBasisEurMinor: group.pnlCoveredCount ? sumPnlCovered(group, "costBasisEurMinor") : null,
      currentValueEurMinor: group.pnlCoveredCount ? sumCovered(group, "eurValueMinor") : null,
      unrealizedPnlMinor: group.unrealizedPnlMinor,
      returnPercent: group.returnPercent,
    }));
}

export function holdingGroupLabel(group: HoldingGroup, groups: HoldingGroup[]): string {
  if (groups.filter((candidate) => candidate.name === group.name).length === 1) return group.name;
  const venue = group.exchange ?? group.micCode ?? group.currency;
  return `${group.name} (${venue})`;
}

function chartLabels(groups: HoldingGroup[]): Map<string, string> {
  return new Map(groups.map((group) => [group.key, holdingGroupLabel(group, groups)]));
}

function groupKey(holding: PortfolioHolding, asset: Asset | undefined): string {
  return asset ? assetPositionKey(asset) : `asset:${holding.assetId}`;
}

function aggregateGroup(key: string, unsortedLots: PortfolioLot[]): HoldingGroup {
  const lots = [...unsortedLots].sort((left, right) => {
    const leftDate = left.asset?.acquisitionDate ?? "";
    const rightDate = right.asset?.acquisitionDate ?? "";
    return leftDate.localeCompare(rightDate) || left.holding.assetId.localeCompare(right.holding.assetId);
  });
  const first = lots[0]!;
  const firstAsset = first.asset;
  const canonicalLot = lots.reduce((oldest, lot) => {
    const oldestCreated = oldest.asset?.createdAt ?? "";
    const lotCreated = lot.asset?.createdAt ?? "";
    return lotCreated && (!oldestCreated || lotCreated < oldestCreated) ? lot : oldest;
  }, first);
  const quote = firstAsset?.quote ?? null;
  const isSecurity = Boolean(firstAsset && SECURITY_TYPES.has(firstAsset.assetType) && quote);
  const valued = lots.filter((lot) => lot.holding.eurValueMinor !== null);
  const costCovered = lots.filter((lot) => lot.holding.costBasisEurMinor !== null);
  const pnlCovered = lots.filter((lot) => lot.holding.unrealizedPnlMinor !== null);
  const evidence = valued.map((lot) => `${lot.holding.source ?? "NONE"}:${lot.holding.valuedAt ?? ""}`);
  const mixedEvidence = new Set(evidence).size > 1;
  const coveredCost = sumNullable(pnlCovered.map((lot) => lot.holding.costBasisEurMinor));
  const unrealizedPnl = sumNullable(pnlCovered.map((lot) => lot.holding.unrealizedPnlMinor));
  return {
    key,
    name: canonicalLot.holding.name,
    assetType: first.holding.assetType,
    currency: first.holding.currency,
    symbol: quote?.symbol ?? null,
    exchange: quote?.exchange ?? null,
    micCode: quote?.micCode ?? null,
    lots,
    quantity: sumDecimals(lots.map((lot) => lot.holding.quantity)),
    nativeValueMinor: sumNullable(valued.map((lot) => lot.holding.nativeValueMinor)),
    eurValueMinor: sumNullable(valued.map((lot) => lot.holding.eurValueMinor)),
    costBasisEurMinor: sumNullable(costCovered.map((lot) => lot.holding.costBasisEurMinor)),
    unrealizedPnlMinor: unrealizedPnl,
    returnPercent:
      unrealizedPnl !== null && coveredCost !== null ? percentage(unrealizedPnl, coveredCost) : null,
    valuedAt: oldestValuationDate(valued),
    source: mixedEvidence ? null : valued[0]?.holding.source ?? null,
    mixedEvidence,
    valuedCount: valued.length,
    costCoveredCount: costCovered.length,
    pnlCoveredCount: pnlCovered.length,
    missingValuation: valued.length !== lots.length,
    isSecurity,
  };
}

function sumCovered(group: HoldingGroup, field: "eurValueMinor"): number | null {
  return sumNullable(
    group.lots
      .filter((lot) => lot.holding.unrealizedPnlMinor !== null)
      .map((lot) => lot.holding[field]),
  );
}

function sumPnlCovered(group: HoldingGroup, field: "costBasisEurMinor"): number | null {
  return sumNullable(
    group.lots
      .filter((lot) => lot.holding.unrealizedPnlMinor !== null)
      .map((lot) => lot.holding[field]),
  );
}

function oldestValuationDate(lots: PortfolioLot[]): string | null {
  const dates = lots
    .map((lot) => lot.holding.valuedAt)
    .filter((value): value is string => value !== null);
  return dates.length ? dates.reduce((oldest, value) => value < oldest ? value : oldest) : null;
}

function sumNullable(values: Array<number | null>): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length ? present.reduce((total, value) => total + value, 0) : null;
}

function sumDecimals(values: Array<string | null>): string | null {
  const present = values.filter((value): value is string => value !== null);
  if (!present.length) return null;
  const parsed = present.map((value) => {
    const [whole = "0", fraction = ""] = value.split(".");
    return { integer: BigInt(`${whole}${fraction}`), scale: fraction.length };
  });
  const scale = Math.max(...parsed.map((value) => value.scale));
  const total = parsed.reduce(
    (sum, value) => sum + value.integer * 10n ** BigInt(scale - value.scale),
    0n,
  );
  const digits = total.toString().padStart(scale + 1, "0");
  if (!scale) return digits;
  const whole = digits.slice(0, -scale);
  const fraction = digits.slice(-scale).replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : whole;
}

function percentage(numerator: number, denominator: number): string | null {
  if (denominator <= 0) return null;
  const scale = 1_000_000n;
  const absolute = BigInt(Math.abs(numerator)) * 100n * scale;
  const divisor = BigInt(denominator);
  const rounded = absolute / divisor + ((absolute % divisor) * 2n >= divisor ? 1n : 0n);
  const whole = rounded / scale;
  const fraction = (rounded % scale).toString().padStart(6, "0").replace(/0+$/, "");
  const rendered = fraction ? `${whole}.${fraction}` : whole.toString();
  return numerator < 0 ? `-${rendered}` : rendered;
}
