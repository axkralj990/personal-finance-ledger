import type { DashboardMonthlyCompositionItem, DashboardRankedCompositionItem } from "../../api/types";

export const LEDGER_PALETTE = [
  "#006D77",
  "#D1495B",
  "#F4A261",
  "#3A86FF",
  "#8338EC",
  "#2A9D8F",
  "#FF006E",
  "#8D6E63",
  "#6A994E",
  "#F26419",
  "#577590",
  "#BC6C25",
  "#00A6A6",
  "#C44536",
  "#4361EE",
  "#7209B7",
] as const;

export const OTHER_TAXONOMY_ID = "__dashboard_other__";

export interface CompositionColumn {
  key: string;
  taxonomyId: string;
  name: string;
  color: string;
  other: boolean;
}

export interface CompositionWideRow {
  period: string;
  partial: boolean;
  [key: string]: string | number | boolean;
}

export interface CompositionChartData {
  columns: CompositionColumn[];
  rows: CompositionWideRow[];
}

export function ledgerColorForId(id: string): string {
  if (id === OTHER_TAXONOMY_ID) return "#8a887f";
  let hash = 2166136261;
  for (let index = 0; index < id.length; index += 1) {
    hash ^= id.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return LEDGER_PALETTE[(hash >>> 0) % LEDGER_PALETTE.length] ?? LEDGER_PALETTE[0];
}

export function buildCompositionChartData(
  monthly: DashboardMonthlyCompositionItem[],
  ranked: DashboardRankedCompositionItem[],
  limit = 8,
  periods: { label: string; partial: boolean }[] = [],
): CompositionChartData {
  const ordered = [...ranked].sort((left, right) =>
    right.amountMinor - left.amountMinor || left.taxonomyId.localeCompare(right.taxonomyId),
  );
  const top = ordered.slice(0, limit);
  const topIds = new Set(top.map((item) => item.taxonomyId));
  const hasOther = monthly.some((item) => !topIds.has(item.taxonomyId));
  const usedColorIndexes = new Set<number>();
  const columns: CompositionColumn[] = top.map((item, index) => {
    const preferred = LEDGER_PALETTE.indexOf(ledgerColorForId(item.taxonomyId) as typeof LEDGER_PALETTE[number]);
    let colorIndex = preferred >= 0 ? preferred : index % LEDGER_PALETTE.length;
    while (usedColorIndexes.has(colorIndex)) colorIndex = (colorIndex + 1) % LEDGER_PALETTE.length;
    usedColorIndexes.add(colorIndex);
    return {
      key: `taxonomy${index}`,
      taxonomyId: item.taxonomyId,
      name: item.name,
      color: LEDGER_PALETTE[colorIndex] ?? LEDGER_PALETTE[0],
      other: false,
    };
  });
  if (hasOther) {
    columns.push({
      key: `taxonomy${columns.length}`,
      taxonomyId: OTHER_TAXONOMY_ID,
      name: "Other",
      color: ledgerColorForId(OTHER_TAXONOMY_ID),
      other: true,
    });
  }

  const keyById = new Map(columns.map((column) => [column.taxonomyId, column.key]));
  const rowsByPeriod = new Map<string, CompositionWideRow>(
    periods.map((period) => [period.label, { period: period.label, partial: period.partial }]),
  );
  for (const item of monthly) {
    const row = rowsByPeriod.get(item.period) ?? { period: item.period, partial: false };
    const key = keyById.get(item.taxonomyId) ?? keyById.get(OTHER_TAXONOMY_ID);
    if (key) row[key] = Number(row[key] ?? 0) + item.amountMinor;
    row.partial = Boolean(row.partial) || item.partial;
    rowsByPeriod.set(item.period, row);
  }
  const rows = [...rowsByPeriod.values()].sort((left, right) => left.period.localeCompare(right.period));
  for (const row of rows) columns.forEach((column) => { row[column.key] ??= 0; });
  return { columns, rows };
}
