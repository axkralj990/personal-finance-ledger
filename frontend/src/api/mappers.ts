import type {
  AllocationItem,
  Asset,
  AssetPnl,
  Category,
  Dashboard,
  DashboardAnnualMonth,
  DashboardAnnualPoint,
  DashboardBoundaryPartials,
  DashboardCumulativePoint,
  DashboardMetricComparison,
  DashboardMonthlyCompositionItem,
  DashboardRankedCompositionItem,
  DashboardRecentTransaction,
  DashboardRollingMeanPoint,
  DashboardSeriesPoint,
  DuplicateState,
  FxPreview,
  Health,
  ImportBatch,
  ImportStatus,
  Page,
  Portfolio,
  PortfolioHistoryPoint,
  PortfolioHolding,
  QuoteHistoryPreview,
  QuotePreviewItem,
  ReportPoint,
  ReportSummary,
  RowDisposition,
  SourceAccount,
  StagedTransaction,
  Subcategory,
  TagRule,
  Transaction,
  TransactionKind,
  Valuation,
} from "./types";

type JsonObject = Record<string, unknown>;

const object = (value: unknown): JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value) ? (value as JsonObject) : {};
const array = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown, fallback = ""): string =>
  typeof value === "string" || typeof value === "number" ? String(value) : fallback;
const number = (value: unknown, fallback = 0): number => {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};
const bool = (value: unknown, fallback = false): boolean =>
  typeof value === "boolean" ? value : value === 1 || value === "true" ? true : fallback;
const nullableText = (value: unknown): string | null => {
  const parsed = text(value);
  return parsed ? parsed : null;
};
const nullableNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const value = (record: JsonObject, ...keys: string[]): unknown => {
  for (const key of keys) {
    if (record[key] !== undefined) return record[key];
  }
  return undefined;
};
const records = (input: unknown): unknown[] => {
  if (Array.isArray(input)) return input;
  const root = object(input);
  return array(value(root, "items", "results", "data", "rows"));
};

export const mapHealth = (input: unknown): Health => ({ status: text(object(input).status, "unknown") });

export const mapSourceAccount = (input: unknown): SourceAccount => {
  const item = object(input);
  return {
    id: text(item.id),
    provider: text(item.provider, "Manual"),
    displayName: text(value(item, "display_name", "displayName", "name"), "Unnamed account"),
    defaultCurrency: text(value(item, "default_currency", "defaultCurrency", "currency"), ""),
    active: bool(value(item, "is_active", "active"), true),
  };
};

export const mapSourceAccounts = (input: unknown): SourceAccount[] => records(input).map(mapSourceAccount);

export const mapImportBatch = (input: unknown): ImportBatch => {
  const item = object(input);
  const counts = object(item.counts);
  return {
    id: text(item.id),
    sourceAccountId: text(value(item, "source_account_id", "sourceAccountId", "account_id")),
    filename: text(value(item, "filename", "original_filename"), "Manual entry"),
    status: text(item.status, "UPLOADED") as ImportStatus,
    totalRows: number(value(item, "total_rows", "totalRows") ?? counts.total),
    validRows: number(value(item, "valid_rows", "validRows") ?? counts.valid),
    needsReviewRows: number(value(item, "needs_review_rows", "needsReviewRows") ?? counts.needs_review),
    duplicateRows: number(value(item, "duplicate_rows", "duplicateRows") ?? counts.duplicates),
    ignoredRows: number(value(item, "ignored_rows", "ignoredRows") ?? counts.ignored),
    errors: array(item.errors).map((entry) => text(object(entry).message ?? entry)).filter(Boolean),
    createdAt: text(value(item, "created_at", "createdAt")),
    updatedAt: text(value(item, "updated_at", "updatedAt")),
  };
};

export const mapImportBatches = (input: unknown): ImportBatch[] => records(input).map(mapImportBatch);

export const mapImportBatchPage = (input: unknown): Page<ImportBatch> => {
  const root = object(input);
  return {
    items: records(input).map(mapImportBatch),
    page: number(root.page, 1),
    pageSize: number(value(root, "page_size", "pageSize"), 50),
    total: number(root.total, records(input).length),
  };
};

export const mapStagedTransaction = (input: unknown): StagedTransaction => {
  const item = object(input);
  const normalized = object(item.normalized);
  const prediction = object(item.prediction);
  const duplicate = object(item.duplicate);
  const errors = array(value(item, "errors", "validation_issues"));
  const disposition = text(item.disposition, bool(item.ignored) ? "IGNORE" : "INCLUDE") as RowDisposition;
  const duplicateState = text(
    value(item, "duplicate_status", "duplicate_state", "duplicateState") ?? duplicate.state,
    "NONE",
  ) as DuplicateState;
  const mappedNormalized = Object.keys(normalized).length ? normalized : {
    transaction_date: value(item, "transaction_date", "date"),
    description: item.description,
    amount_minor: value(item, "amount_minor", "amountMinor"),
    currency: item.currency,
    kind: item.kind,
  };
  return {
    id: text(item.id),
    rowNumber: number(value(item, "row_number", "rowNumber")),
    revision: number(item.revision),
    date: nullableText(value(item, "date", "transaction_date") ?? normalized.date ?? normalized.transaction_date),
    description: nullableText(item.description ?? normalized.description),
    amountMinor: nullableNumber(value(item, "amount_minor", "amountMinor") ?? normalized.amount_minor),
    currency: nullableText(item.currency ?? normalized.currency),
    kind: nullableText(item.kind ?? normalized.kind) as TransactionKind | null,
    categoryId: nullableText(value(item, "category_id", "categoryId")),
    subcategoryId: nullableText(value(item, "subcategory_id", "subcategoryId")),
    predictedCategoryId: nullableText(value(item, "predicted_category_id", "predictedCategoryId") ?? prediction.category_id),
    predictedSubcategoryId: nullableText(value(item, "predicted_subcategory_id", "predictedSubcategoryId") ?? prediction.subcategory_id),
    confidence: value(item, "prediction_confidence", "confidence") === undefined && prediction.confidence === undefined
      ? null
      : number(value(item, "prediction_confidence", "confidence") ?? prediction.confidence),
    duplicateState,
    duplicateExplanation: nullableText(value(item, "duplicate_explanation", "duplicateExplanation") ?? duplicate.explanation),
    duplicateCandidate: Object.keys(object(value(item, "duplicate_candidate", "duplicateCandidate") ?? duplicate.candidate)).length
      ? object(value(item, "duplicate_candidate", "duplicateCandidate") ?? duplicate.candidate)
      : null,
    disposition,
    ignoreReason: nullableText(value(item, "ignore_reason", "ignoreReason")),
    rememberCorrection: bool(value(item, "remember_correction", "rememberCorrection")),
    needsReview: bool(
      value(item, "needs_review", "needsReview"),
      disposition === "PENDING" || disposition === "BLOCKED" || errors.length > 0 || duplicateState === "LIKELY",
    ),
    errors: errors.map((entry) => text(object(entry).message ?? entry)).filter(Boolean),
    raw: object(value(item, "raw_json", "raw", "raw_data")),
    normalized: mappedNormalized,
  };
};

export const mapStagedTransactions = (input: unknown): StagedTransaction[] => records(input).map(mapStagedTransaction);

export const mapStagedTransactionPage = (input: unknown): Page<StagedTransaction> => {
  const root = object(input);
  return {
    items: records(input).map(mapStagedTransaction),
    page: number(root.page, 1),
    pageSize: number(value(root, "page_size", "pageSize"), 100),
    total: number(root.total, records(input).length),
  };
};

export const mapSubcategory = (input: unknown, categoryId = ""): Subcategory => {
  const item = object(input);
  return {
    id: text(item.id),
    categoryId: text(value(item, "category_id", "categoryId"), categoryId),
    name: text(value(item, "display_name", "name"), "Untitled"),
    sortOrder: number(value(item, "sort_order", "sortOrder")),
    active: bool(value(item, "is_active", "active"), true),
  };
};

export const mapCategory = (input: unknown): Category => {
  const item = object(input);
  const categoryId = text(item.id);
  return {
    id: categoryId,
    name: text(value(item, "display_name", "name"), "Untitled"),
    sortOrder: number(value(item, "sort_order", "sortOrder")),
    active: bool(value(item, "is_active", "active"), true),
    subcategories: array(value(item, "subcategories", "children")).map((entry) => mapSubcategory(entry, categoryId)),
  };
};

export const mapCategories = (input: unknown): Category[] => records(input).map(mapCategory);

export const mapTagRule = (input: unknown): TagRule => {
  const item = object(input);
  return {
    id: text(item.id),
    match: text(value(item, "match", "normalized_description", "description")),
    scope: text(item.scope, "GLOBAL"),
    provider: nullableText(item.provider),
    sourceAccountId: nullableText(value(item, "source_account_id", "sourceAccountId")),
    categoryId: text(value(item, "category_id", "categoryId")),
    subcategoryId: nullableText(value(item, "subcategory_id", "subcategoryId")),
    active: bool(value(item, "is_enabled", "active"), true),
  };
};

export const mapTagRules = (input: unknown): TagRule[] => records(input).map(mapTagRule);

export const mapCurrencies = (input: unknown): string[] => {
  const root = object(input);
  const values = Array.isArray(input) ? input : array(value(root, "currencies", "items", "data"));
  return [...new Set(values.map((entry) => {
    const item = object(entry);
    return text(value(item, "currency", "code", "value") ?? entry).toUpperCase();
  }).filter(Boolean))];
};

export const mapTransaction = (input: unknown): Transaction => {
  const item = object(input);
  const account = object(value(item, "source_account", "account"));
  const category = object(item.category);
  const subcategory = object(item.subcategory);
  return {
    id: text(item.id),
    revision: number(item.revision),
    date: text(value(item, "date", "transaction_date")),
    description: text(item.description),
    amountMinor: number(value(item, "amount_minor", "amountMinor")),
    currency: text(item.currency),
    kind: text(item.kind, "EXPENSE") as TransactionKind,
    sourceAccountId: text(value(item, "source_account_id", "sourceAccountId") ?? account.id),
    sourceAccountName: text(value(item, "source_account_name", "sourceAccountName") ?? account.display_name ?? account.name),
    categoryId: nullableText(value(item, "category_id", "categoryId") ?? category.id),
    categoryName: nullableText(value(item, "category_name", "categoryName") ?? category.display_name ?? category.name),
    subcategoryId: nullableText(value(item, "subcategory_id", "subcategoryId") ?? subcategory.id),
    subcategoryName: nullableText(value(item, "subcategory_name", "subcategoryName") ?? subcategory.display_name ?? subcategory.name),
    excluded: bool(value(item, "is_excluded", "excluded")),
    importBatchId: nullableText(value(item, "import_batch_id", "importBatchId")),
  };
};

export const mapTransactionPage = (input: unknown): Page<Transaction> => {
  const root = object(input);
  return {
    items: records(input).map(mapTransaction),
    page: number(root.page, 1),
    pageSize: number(value(root, "page_size", "pageSize"), 25),
    total: number(root.total, records(input).length),
  };
};

export const mapReportSummary = (input: unknown): ReportSummary => {
  const item = object(input);
  return {
    currency: text(item.currency),
    incomeMinor: number(value(item, "income_minor", "incomeMinor", "income")),
    spendingMinor: number(value(item, "spending_minor", "spendingMinor", "spending")),
    netMinor: number(value(item, "net_flow_minor", "net_minor", "netMinor", "net")),
  };
};

export const mapReportPoints = (input: unknown): ReportPoint[] =>
  records(input).map((entry) => {
    const item = object(entry);
    return {
      label: text(value(item, "label", "name", "date", "period", "account_name")),
      amountMinor: number(value(item, "amount_minor", "amountMinor", "amount", "value")),
    };
  });

const mapBoundaryPartials = (input: unknown): DashboardBoundaryPartials => {
  const item = object(input);
  return { first: bool(item.first), last: bool(item.last) };
};

const mapMetricComparison = (input: unknown): DashboardMetricComparison => {
  const item = object(input);
  return {
    currentMinor: number(value(item, "current_minor", "currentMinor")),
    priorMinor: number(value(item, "prior_minor", "priorMinor")),
    deltaMinor: number(value(item, "delta_minor", "deltaMinor")),
    deltaPercent: nullableNumber(value(item, "delta_percent", "deltaPercent")),
  };
};

const mapDashboardSeriesPoint = (input: unknown): DashboardSeriesPoint => {
  const item = object(input);
  return {
    periodStart: text(value(item, "period_start", "periodStart")),
    periodEnd: text(value(item, "period_end", "periodEnd")),
    label: text(item.label),
    partial: bool(item.partial),
    selectedDays: number(value(item, "selected_days", "selectedDays")),
    incomeTotalMinor: number(value(item, "income_total_minor", "incomeTotalMinor")),
    spendingTotalMinor: number(value(item, "spending_total_minor", "spendingTotalMinor")),
    netTotalMinor: number(value(item, "net_total_minor", "netTotalMinor")),
  };
};

const mapRollingMeanPoint = (input: unknown): DashboardRollingMeanPoint => {
  const item = object(input);
  return {
    date: text(item.date),
    windowStart: text(value(item, "window_start", "windowStart")),
    windowEnd: text(value(item, "window_end", "windowEnd")),
    windowMonths: number(value(item, "window_months", "windowMonths")),
    incomeMeanMinor: number(value(item, "income_mean_minor", "incomeMeanMinor")),
    spendingMeanMinor: number(value(item, "spending_mean_minor", "spendingMeanMinor")),
    netMeanMinor: number(value(item, "net_mean_minor", "netMeanMinor")),
  };
};

const mapMonthlyCompositionItem = (input: unknown): DashboardMonthlyCompositionItem => {
  const item = object(input);
  return {
    period: text(item.period),
    taxonomyId: text(value(item, "taxonomy_id", "taxonomyId")),
    name: text(item.name),
    amountMinor: number(value(item, "amount_minor", "amountMinor")),
    count: number(item.count),
    partial: bool(item.partial),
  };
};

const mapRankedCompositionItem = (input: unknown): DashboardRankedCompositionItem => {
  const item = object(input);
  return {
    taxonomyId: text(value(item, "taxonomy_id", "taxonomyId")),
    name: text(item.name),
    amountMinor: number(value(item, "amount_minor", "amountMinor")),
    count: number(item.count),
    percentage: number(item.percentage),
  };
};

const mapAnnualMonth = (input: unknown): DashboardAnnualMonth => {
  const item = object(input);
  return {
    month: number(item.month),
    incomeTotalMinor: number(value(item, "income_total_minor", "incomeTotalMinor")),
    spendingTotalMinor: number(value(item, "spending_total_minor", "spendingTotalMinor")),
    netTotalMinor: number(value(item, "net_total_minor", "netTotalMinor")),
  };
};

const mapAnnualPoint = (input: unknown): DashboardAnnualPoint => {
  const item = object(input);
  return {
    year: number(item.year),
    partial: bool(item.partial),
    incomeTotalMinor: number(value(item, "income_total_minor", "incomeTotalMinor")),
    spendingTotalMinor: number(value(item, "spending_total_minor", "spendingTotalMinor")),
    netTotalMinor: number(value(item, "net_total_minor", "netTotalMinor")),
    incomeMonthlyMeanMinor: number(value(item, "income_monthly_mean_minor", "incomeMonthlyMeanMinor")),
    spendingMonthlyMeanMinor: number(value(item, "spending_monthly_mean_minor", "spendingMonthlyMeanMinor")),
    netMonthlyMeanMinor: number(value(item, "net_monthly_mean_minor", "netMonthlyMeanMinor")),
    months: array(item.months).map(mapAnnualMonth),
  };
};

const mapCumulativePoint = (input: unknown): DashboardCumulativePoint => {
  const item = object(input);
  return {
    date: text(item.date),
    netMinor: number(value(item, "net_minor", "netMinor")),
    cumulativeMinor: number(value(item, "cumulative_minor", "cumulativeMinor")),
  };
};

const mapDashboardRecent = (input: unknown): DashboardRecentTransaction => {
  const item = object(input);
  return {
    id: text(item.id),
    date: text(item.date),
    description: text(item.description),
    amountMinor: number(value(item, "amount_minor", "amountMinor")),
    kind: text(item.kind, "EXPENSE") as TransactionKind,
    categoryId: nullableText(value(item, "category_id", "categoryId")),
    categoryName: nullableText(value(item, "category_name", "categoryName")),
    subcategoryId: nullableText(value(item, "subcategory_id", "subcategoryId")),
    subcategoryName: nullableText(value(item, "subcategory_name", "subcategoryName")),
    sourceAccountId: text(value(item, "source_account_id", "sourceAccountId")),
    sourceAccountName: text(value(item, "source_account_name", "sourceAccountName")),
  };
};

export const mapDashboard = (input: unknown): Dashboard => {
  const root = object(input);
  const meta = object(root.meta);
  const partialPeriods = object(value(meta, "partial_periods", "partialPeriods"));
  const summary = object(root.summary);
  const series = object(root.series);
  const rollingMean = object(value(series, "rolling_mean", "rollingMean"));
  const composition = object(root.composition);
  const quality = object(root.quality);
  return {
    meta: {
      dateFrom: text(value(meta, "date_from", "dateFrom")),
      dateTo: text(value(meta, "date_to", "dateTo")),
      priorFrom: text(value(meta, "prior_from", "priorFrom")),
      priorTo: text(value(meta, "prior_to", "priorTo")),
      dataFrom: nullableText(value(meta, "data_from", "dataFrom")),
      dataTo: nullableText(value(meta, "data_to", "dataTo")),
      generatedAt: text(value(meta, "generated_at", "generatedAt")),
      currency: text(meta.currency, "EUR"),
      selectedCategoryIds: array(value(meta, "selected_category_ids", "selectedCategoryIds")).map((entry) => text(entry)),
      selectedSubcategoryIds: array(value(meta, "selected_subcategory_ids", "selectedSubcategoryIds")).map((entry) => text(entry)),
      partialPeriods: {
        week: mapBoundaryPartials(partialPeriods.week),
        month: mapBoundaryPartials(partialPeriods.month),
        quarter: mapBoundaryPartials(partialPeriods.quarter),
        year: mapBoundaryPartials(partialPeriods.year),
      },
    },
    summary: {
      income: mapMetricComparison(summary.income),
      spending: mapMetricComparison(summary.spending),
      net: mapMetricComparison(summary.net),
      monthlySpendingMean: mapMetricComparison(value(summary, "monthly_spending_mean", "monthlySpendingMean")),
    },
    series: {
      week: array(series.week).map(mapDashboardSeriesPoint),
      month: array(series.month).map(mapDashboardSeriesPoint),
      quarter: array(series.quarter).map(mapDashboardSeriesPoint),
      rollingMean: {
        month: array(rollingMean.month).map(mapRollingMeanPoint),
        quarter: array(rollingMean.quarter).map(mapRollingMeanPoint),
        year: array(rollingMean.year).map(mapRollingMeanPoint),
      },
    },
    composition: {
      categoryMonthly: array(value(composition, "category_monthly", "categoryMonthly")).map(mapMonthlyCompositionItem),
      subcategoryMonthly: array(value(composition, "subcategory_monthly", "subcategoryMonthly")).map(mapMonthlyCompositionItem),
      categoryRanked: array(value(composition, "category_ranked", "categoryRanked")).map(mapRankedCompositionItem),
      subcategoryRanked: array(value(composition, "subcategory_ranked", "subcategoryRanked")).map(mapRankedCompositionItem),
    },
    annual: array(root.annual).map(mapAnnualPoint),
    cumulative: array(root.cumulative).map(mapCumulativePoint),
    recent: array(root.recent).map(mapDashboardRecent),
    quality: {
      transactionCount: number(value(quality, "transaction_count", "transactionCount")),
      uncategorizedCount: number(value(quality, "uncategorized_count", "uncategorizedCount")),
      categoryOnlyCount: number(value(quality, "category_only_count", "categoryOnlyCount")),
    },
  };
};

export const mapValuation = (input: unknown): Valuation => {
  const item = object(input);
  return {
    id: text(item.id),
    assetId: text(value(item, "asset_id", "assetId")),
    valuedAt: text(value(item, "valued_at", "valuedAt")),
    nativeValueMinor: number(value(item, "native_value_minor", "nativeValueMinor")),
    eurValueMinor: number(value(item, "eur_value_minor", "eurValueMinor")),
    quantity: nullableText(item.quantity),
    unitPrice: nullableText(value(item, "unit_price", "unitPrice")),
    costBasisNativeMinor: nullableNumber(value(item, "cost_basis_native_minor", "costBasisNativeMinor")),
    costBasisEurMinor: nullableNumber(value(item, "cost_basis_eur_minor", "costBasisEurMinor")),
    costBasisFxSource: nullableText(value(item, "cost_basis_fx_source", "costBasisFxSource")),
    costBasisFxRateToEur: nullableText(value(item, "cost_basis_fx_rate_to_eur", "costBasisFxRateToEur")),
    costBasisFxRateDate: nullableText(value(item, "cost_basis_fx_rate_date", "costBasisFxRateDate")),
    source: text(item.source, "MANUAL") as Valuation["source"],
    quoteSymbol: nullableText(value(item, "quote_symbol", "quoteSymbol")),
    quoteExchange: nullableText(value(item, "quote_exchange", "quoteExchange")),
    quoteMicCode: nullableText(value(item, "quote_mic_code", "quoteMicCode")),
    quoteName: nullableText(value(item, "quote_name", "quoteName")),
    quoteFetchedAt: nullableText(value(item, "quote_fetched_at", "quoteFetchedAt")),
    quoteInterval: nullableText(value(item, "quote_interval", "quoteInterval")) as Valuation["quoteInterval"],
    fxSource: text(value(item, "fx_source", "fxSource")),
    fxRateToEur: text(value(item, "fx_rate_to_eur", "fxRateToEur")),
    fxRateDate: text(value(item, "fx_rate_date", "fxRateDate")),
    createdAt: text(value(item, "created_at", "createdAt")),
  };
};

export const mapAsset = (input: unknown): Asset => {
  const item = object(input);
  const quote = object(item.quote);
  const latest = value(item, "latest_valuation", "latestValuation");
  return {
    id: text(item.id),
    name: text(item.name, "Unnamed asset"),
    assetType: text(value(item, "asset_type", "assetType"), "OTHER") as Asset["assetType"],
    currency: text(item.currency),
    acquisitionDate: text(value(item, "acquisition_date", "acquisitionDate")),
    quantity: nullableText(item.quantity),
    costBasisNativeMinor: nullableNumber(value(item, "cost_basis_native_minor", "costBasisNativeMinor")),
    costBasisEurMinor: nullableNumber(value(item, "cost_basis_eur_minor", "costBasisEurMinor")),
    costBasisFxSource: nullableText(value(item, "cost_basis_fx_source", "costBasisFxSource")),
    costBasisFxRateToEur: nullableText(value(item, "cost_basis_fx_rate_to_eur", "costBasisFxRateToEur")),
    costBasisFxRateDate: nullableText(value(item, "cost_basis_fx_rate_date", "costBasisFxRateDate")),
    quote: Object.keys(quote).length ? {
      symbol: text(quote.symbol),
      exchange: nullableText(quote.exchange),
      micCode: nullableText(value(quote, "mic_code", "micCode")),
    } : null,
    isActive: bool(value(item, "is_active", "isActive"), true),
    revision: number(item.revision, 1),
    createdAt: text(value(item, "created_at", "createdAt")),
    updatedAt: text(value(item, "updated_at", "updatedAt")),
    archivedAt: nullableText(value(item, "archived_at", "archivedAt")),
    archivedOn: nullableText(value(item, "archived_on", "archivedOn")),
    latestValuation: latest == null ? null : mapValuation(latest),
  };
};

export const mapAssets = (input: unknown): Asset[] => records(input).map(mapAsset);
export const mapValuations = (input: unknown): Valuation[] => records(input).map(mapValuation);

const mapAllocation = (input: unknown): AllocationItem => {
  const item = object(input);
  return { key: text(item.key), name: text(item.name), valueMinor: number(value(item, "value_minor", "valueMinor")), percentage: nullableText(item.percentage) };
};

const mapAssetPnl = (input: unknown): AssetPnl => {
  const item = object(input);
  return {
    assetId: text(value(item, "asset_id", "assetId")),
    name: text(item.name),
    costBasisEurMinor: nullableNumber(value(item, "cost_basis_eur_minor", "costBasisEurMinor")),
    currentValueEurMinor: nullableNumber(value(item, "current_value_eur_minor", "currentValueEurMinor")),
    unrealizedPnlMinor: nullableNumber(value(item, "unrealized_pnl_minor", "unrealizedPnlMinor")),
    returnPercent: nullableText(value(item, "return_percent", "returnPercent")),
  };
};

const mapHolding = (input: unknown): PortfolioHolding => {
  const item = object(input);
  return {
    assetId: text(value(item, "asset_id", "assetId")), name: text(item.name),
    assetType: text(value(item, "asset_type", "assetType"), "OTHER") as PortfolioHolding["assetType"],
    currency: text(item.currency), revision: number(item.revision, 1), quantity: nullableText(item.quantity),
    valuationId: nullableText(value(item, "valuation_id", "valuationId")), valuedAt: nullableText(value(item, "valued_at", "valuedAt")),
    source: nullableText(item.source) as PortfolioHolding["source"],
    nativeValueMinor: nullableNumber(value(item, "native_value_minor", "nativeValueMinor")),
    eurValueMinor: nullableNumber(value(item, "eur_value_minor", "eurValueMinor")),
    costBasisEurMinor: nullableNumber(value(item, "cost_basis_eur_minor", "costBasisEurMinor")),
    unrealizedPnlMinor: nullableNumber(value(item, "unrealized_pnl_minor", "unrealizedPnlMinor")),
    returnPercent: nullableText(value(item, "return_percent", "returnPercent")),
    missingValuation: bool(value(item, "missing_valuation", "missingValuation")),
  };
};

const mapHistoryPoint = (input: unknown): PortfolioHistoryPoint => {
  const item = object(input);
  return {
    date: text(item.date), complete: bool(item.complete),
    knownValueMinor: number(value(item, "known_value_minor", "knownValueMinor")),
    totalValueMinor: nullableNumber(value(item, "total_value_minor", "totalValueMinor")),
    trackedCostBasisMinor: nullableNumber(value(item, "tracked_cost_basis_minor", "trackedCostBasisMinor")),
    unrealizedPnlMinor: nullableNumber(value(item, "unrealized_pnl_minor", "unrealizedPnlMinor")),
    pnlEligibleAssets: number(value(item, "pnl_eligible_assets", "pnlEligibleAssets")),
    pnlCoveredAssets: number(value(item, "pnl_covered_assets", "pnlCoveredAssets")),
  };
};

export const mapPortfolio = (input: unknown): Portfolio => {
  const item = object(input);
  return {
    asOf: text(value(item, "as_of", "asOf")), generatedAt: text(value(item, "generated_at", "generatedAt")), currency: "EUR",
    complete: bool(item.complete), missingAssetIds: array(value(item, "missing_asset_ids", "missingAssetIds")).map((entry) => text(entry)),
    assetCount: number(value(item, "asset_count", "assetCount")), valuedAssetCount: number(value(item, "valued_asset_count", "valuedAssetCount")),
    knownValueMinor: number(value(item, "known_value_minor", "knownValueMinor")), totalValueMinor: nullableNumber(value(item, "total_value_minor", "totalValueMinor")),
    trackedCostBasisMinor: nullableNumber(value(item, "tracked_cost_basis_minor", "trackedCostBasisMinor")),
    unrealizedPnlMinor: nullableNumber(value(item, "unrealized_pnl_minor", "unrealizedPnlMinor")), returnPercent: nullableText(value(item, "return_percent", "returnPercent")),
    pnlEligibleAssets: number(value(item, "pnl_eligible_assets", "pnlEligibleAssets")), pnlCoveredAssets: number(value(item, "pnl_covered_assets", "pnlCoveredAssets")),
    allocationByType: array(value(item, "allocation_by_type", "allocationByType")).map(mapAllocation),
    allocationByAsset: array(value(item, "allocation_by_asset", "allocationByAsset")).map(mapAllocation),
    pnlByAsset: array(value(item, "pnl_by_asset", "pnlByAsset")).map(mapAssetPnl),
    holdings: array(item.holdings).map(mapHolding), history: array(item.history).map(mapHistoryPoint),
  };
};

export const mapQuotePreviewItem = (input: unknown): QuotePreviewItem => {
  const item = object(input);
  const status = text(item.status);
  if (status === "error") {
    const error = object(item.error);
    if (!text(value(item, "asset_id", "assetId")) || !text(error.code) || !text(error.message)) throw new Error("Error quote preview response is malformed.");
    return { status: "error", assetId: text(value(item, "asset_id", "assetId")), assetRevision: nullableNumber(value(item, "asset_revision", "assetRevision")), error: { code: text(error.code), message: text(error.message), recoverable: bool(error.recoverable) } };
  }
  if (status !== "ready") throw new Error("Quote preview response has an unknown or missing status.");
  const quote = object(item.quote); const fx = object(item.fx);
  const nativeValueMinor = nullableNumber(value(item, "native_value_minor", "nativeValueMinor"));
  const eurValueMinor = nullableNumber(value(item, "eur_value_minor", "eurValueMinor"));
  const previewToken = text(value(item, "preview_token", "previewToken"));
  const assetId = text(value(item, "asset_id", "assetId"));
  const assetRevision = nullableNumber(value(item, "asset_revision", "assetRevision"));
  const valuedAt = text(value(item, "valued_at", "valuedAt"));
  const nativeCurrency = text(value(item, "native_currency", "nativeCurrency"));
  const quantity = text(item.quantity);
  const unitPrice = text(value(item, "unit_price", "unitPrice"));
  const quoteSymbol = text(quote.symbol);
  const quoteExchange = nullableText(quote.exchange);
  const quoteMicCode = nullableText(value(quote, "mic_code", "micCode"));
  const quoteName = text(quote.name);
  const quoteFetchedAt = text(value(quote, "fetched_at", "fetchedAt"));
  const fxSource = text(fx.source);
  const fxRate = text(value(fx, "rate_to_eur", "rateToEur"));
  const fxDate = text(value(fx, "rate_date", "rateDate"));
  const source = text(item.source);
  const quoteInterval = text(value(item, "quote_interval", "quoteInterval"), "LIVE");
  if ((source !== "TWELVE_DATA" && source !== "YAHOO_FINANCE") || (quoteInterval !== "LIVE" && quoteInterval !== "MONTHLY") || !assetId || !Number.isSafeInteger(assetRevision) || assetRevision! < 1 || !valuedAt || !nativeCurrency || !DECIMAL_SAFE(quantity) || !DECIMAL_SAFE(unitPrice) || !quoteSymbol || (!quoteExchange && !quoteMicCode) || !quoteName || !quoteFetchedAt || (fxSource !== "ECB" && fxSource !== "IDENTITY") || !DECIMAL_SAFE(fxRate) || !fxDate || !Number.isSafeInteger(nativeValueMinor) || !Number.isSafeInteger(eurValueMinor) || nativeValueMinor! < 0 || eurValueMinor! < 0 || previewToken.length !== 64) {
    throw new Error("Ready quote preview response is malformed.");
  }
  return {
    status: "ready", assetId, assetRevision: assetRevision!, source, quoteInterval,
    valuedAt, nativeCurrency,
    nativeValueMinor: nativeValueMinor!, eurValueMinor: eurValueMinor!,
    quantity, unitPrice,
    quote: { symbol: quoteSymbol, exchange: quoteExchange, micCode: quoteMicCode, name: quoteName, fetchedAt: quoteFetchedAt },
    fx: { source: fxSource, rateToEur: fxRate, rateDate: fxDate },
    previewToken,
  };
};

const DECIMAL_SAFE = (input: string) => /^(?:0|[1-9]\d*)(?:\.\d*[1-9])?$/.test(input);

export const mapQuotePreview = (input: unknown): QuotePreviewItem[] => {
  const items = object(input).items;
  if (!Array.isArray(items)) throw new Error("Quote preview response is malformed.");
  return items.map(mapQuotePreviewItem);
};

export const mapQuoteHistoryPreview = (input: unknown): QuoteHistoryPreview => {
  const item = object(input);
  const assetId = text(value(item, "asset_id", "assetId"));
  const assetRevision = nullableNumber(value(item, "asset_revision", "assetRevision"));
  const source = text(item.source);
  const availableMonths = nullableNumber(value(item, "available_months", "availableMonths"));
  const existingMonths = nullableNumber(value(item, "existing_months", "existingMonths"));
  const previews = mapQuotePreview({ items: array(item.items) });
  if (!assetId || !Number.isSafeInteger(assetRevision) || assetRevision! < 1 || source !== "YAHOO_FINANCE" || !Number.isSafeInteger(availableMonths) || availableMonths! < 0 || !Number.isSafeInteger(existingMonths) || existingMonths! < 0 || previews.some((preview) => preview.status !== "ready" || preview.quoteInterval !== "MONTHLY")) {
    throw new Error("Quote history preview response is malformed.");
  }
  return {
    assetId,
    assetRevision: assetRevision!,
    source,
    availableMonths: availableMonths!,
    existingMonths: existingMonths!,
    firstDate: nullableText(value(item, "first_date", "firstDate")),
    lastDate: nullableText(value(item, "last_date", "lastDate")),
    items: previews as QuoteHistoryPreview["items"],
  };
};

export const mapFxPreview = (input: unknown): FxPreview => {
  const item = object(input);
  const currency = text(item.currency);
  const valuedAt = text(value(item, "valued_at", "valuedAt"));
  const source = text(item.source);
  const rateToEur = text(value(item, "rate_to_eur", "rateToEur"));
  const rateDate = text(value(item, "rate_date", "rateDate"));
  const previewToken = text(value(item, "preview_token", "previewToken"));
  if (!currency || !valuedAt || (source !== "ECB" && source !== "IDENTITY") || !rateToEur || !rateDate || previewToken.length !== 64) throw new Error("FX preview response is malformed.");
  return { currency, valuedAt, source, rateToEur, rateDate, previewToken };
};
