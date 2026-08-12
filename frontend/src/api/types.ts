export type Identifier = string;

export type TransactionKind = "EXPENSE" | "INCOME" | "REFUND" | "FEE" | "TRANSFER";
export type ImportStatus =
  | "UPLOADED"
  | "PARSED"
  | "NEEDS_REVIEW"
  | "READY"
  | "COMMITTED"
  | "FAILED"
  | "DELETED";
export type DuplicateState = "NONE" | "LIKELY" | "EXACT";
export type RowDisposition =
  | "PENDING"
  | "INCLUDE"
  | "IGNORE"
  | "BLOCKED"
  | "AUDIT_ONLY"
  | "COMMITTED";

export interface SourceAccount {
  id: Identifier;
  provider: string;
  displayName: string;
  defaultCurrency: string;
  active: boolean;
}

export interface ImportBatch {
  id: Identifier;
  sourceAccountId: Identifier;
  filename: string;
  status: ImportStatus;
  totalRows: number;
  validRows: number;
  needsReviewRows: number;
  duplicateRows: number;
  ignoredRows: number;
  errors: string[];
  createdAt: string;
  updatedAt: string;
}

export interface StagedTransaction {
  id: Identifier;
  rowNumber: number;
  revision: number;
  date: string | null;
  description: string | null;
  amountMinor: number | null;
  currency: string | null;
  kind: TransactionKind | null;
  categoryId: Identifier | null;
  subcategoryId: Identifier | null;
  predictedCategoryId: Identifier | null;
  predictedSubcategoryId: Identifier | null;
  confidence: number | null;
  duplicateState: DuplicateState;
  duplicateExplanation: string | null;
  duplicateCandidate: Record<string, unknown> | null;
  disposition: RowDisposition;
  ignoreReason: string | null;
  rememberCorrection: boolean;
  needsReview: boolean;
  errors: string[];
  raw: Record<string, unknown>;
  normalized: Record<string, unknown>;
}

export interface StagedRowPatch {
  id: Identifier;
  expectedRevision: number;
  transactionDate?: string | null;
  description?: string | null;
  amountMinor?: number | null;
  currency?: string | null;
  categoryId?: Identifier | null;
  subcategoryId?: Identifier | null;
  disposition?: RowDisposition;
  ignoreReason?: string | null;
  rememberCorrection?: boolean;
}

export interface Category {
  id: Identifier;
  name: string;
  sortOrder: number;
  active: boolean;
  subcategories: Subcategory[];
}

export interface Subcategory {
  id: Identifier;
  categoryId: Identifier;
  name: string;
  sortOrder: number;
  active: boolean;
}

export interface TagRule {
  id: Identifier;
  match: string;
  scope: string;
  provider: string | null;
  sourceAccountId: Identifier | null;
  categoryId: Identifier;
  subcategoryId: Identifier | null;
  active: boolean;
}

export interface Transaction {
  id: Identifier;
  revision: number;
  date: string;
  description: string;
  amountMinor: number;
  currency: string;
  kind: TransactionKind;
  sourceAccountId: Identifier;
  sourceAccountName: string;
  categoryId: Identifier | null;
  categoryName: string | null;
  subcategoryId: Identifier | null;
  subcategoryName: string | null;
  excluded: boolean;
  importBatchId: Identifier | null;
}

export interface Page<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}

export interface TransactionQuery {
  page?: number;
  pageSize?: number;
  currency?: string;
  dateFrom?: string;
  dateTo?: string;
  sourceAccountId?: Identifier;
  categoryId?: Identifier;
  search?: string;
  includeExcluded?: boolean;
}

export interface ReportQuery {
  currency: string;
  dateFrom?: string;
  dateTo?: string;
}

export interface ReportSummary {
  currency: string;
  incomeMinor: number;
  spendingMinor: number;
  netMinor: number;
}

export interface ReportPoint {
  label: string;
  amountMinor: number;
}

export interface DashboardQuery {
  dateFrom: string;
  dateTo: string;
  categoryIds?: Identifier[];
  subcategoryIds?: Identifier[];
}

export interface DashboardBoundaryPartials {
  first: boolean;
  last: boolean;
}

export interface DashboardPartialPeriods {
  week: DashboardBoundaryPartials;
  month: DashboardBoundaryPartials;
  quarter: DashboardBoundaryPartials;
  year: DashboardBoundaryPartials;
}

export interface DashboardMeta {
  dateFrom: string;
  dateTo: string;
  priorFrom: string;
  priorTo: string;
  dataFrom: string | null;
  dataTo: string | null;
  generatedAt: string;
  currency: string;
  selectedCategoryIds: Identifier[];
  selectedSubcategoryIds: Identifier[];
  partialPeriods: DashboardPartialPeriods;
}

export interface DashboardMetricComparison {
  currentMinor: number;
  priorMinor: number;
  deltaMinor: number;
  deltaPercent: number | null;
}

export interface DashboardSummary {
  income: DashboardMetricComparison;
  spending: DashboardMetricComparison;
  net: DashboardMetricComparison;
  monthlySpendingMean: DashboardMetricComparison;
}

export interface DashboardSeriesPoint {
  periodStart: string;
  periodEnd: string;
  label: string;
  partial: boolean;
  selectedDays: number;
  incomeTotalMinor: number;
  spendingTotalMinor: number;
  netTotalMinor: number;
}

export interface DashboardRollingMeanPoint {
  date: string;
  windowStart: string;
  windowEnd: string;
  windowMonths: number;
  incomeMeanMinor: number;
  spendingMeanMinor: number;
  netMeanMinor: number;
}

export interface DashboardRollingMeanSeries {
  month: DashboardRollingMeanPoint[];
  quarter: DashboardRollingMeanPoint[];
  year: DashboardRollingMeanPoint[];
}

export interface DashboardSeries {
  week: DashboardSeriesPoint[];
  month: DashboardSeriesPoint[];
  quarter: DashboardSeriesPoint[];
  rollingMean: DashboardRollingMeanSeries;
}

export interface DashboardMonthlyCompositionItem {
  period: string;
  taxonomyId: Identifier;
  name: string;
  amountMinor: number;
  count: number;
  partial: boolean;
}

export interface DashboardRankedCompositionItem {
  taxonomyId: Identifier;
  name: string;
  amountMinor: number;
  count: number;
  percentage: number;
}

export interface DashboardComposition {
  categoryMonthly: DashboardMonthlyCompositionItem[];
  subcategoryMonthly: DashboardMonthlyCompositionItem[];
  categoryRanked: DashboardRankedCompositionItem[];
  subcategoryRanked: DashboardRankedCompositionItem[];
}

export interface DashboardAnnualMonth {
  month: number;
  incomeTotalMinor: number;
  spendingTotalMinor: number;
  netTotalMinor: number;
}

export interface DashboardAnnualPoint {
  year: number;
  partial: boolean;
  incomeTotalMinor: number;
  spendingTotalMinor: number;
  netTotalMinor: number;
  incomeMonthlyMeanMinor: number;
  spendingMonthlyMeanMinor: number;
  netMonthlyMeanMinor: number;
  months: DashboardAnnualMonth[];
}

export interface DashboardCumulativePoint {
  date: string;
  netMinor: number;
  cumulativeMinor: number;
}

export interface DashboardRecentTransaction {
  id: Identifier;
  date: string;
  description: string;
  amountMinor: number;
  kind: TransactionKind;
  categoryId: Identifier | null;
  categoryName: string | null;
  subcategoryId: Identifier | null;
  subcategoryName: string | null;
  sourceAccountId: Identifier;
  sourceAccountName: string;
}

export interface DashboardQuality {
  transactionCount: number;
  uncategorizedCount: number;
  categoryOnlyCount: number;
}

export interface Dashboard {
  meta: DashboardMeta;
  summary: DashboardSummary;
  series: DashboardSeries;
  composition: DashboardComposition;
  annual: DashboardAnnualPoint[];
  cumulative: DashboardCumulativePoint[];
  recent: DashboardRecentTransaction[];
  quality: DashboardQuality;
}

export interface ManualTransactionInput {
  sourceAccountId: Identifier;
  date: string;
  description: string;
  amountMinor: number;
  currency: string;
  categoryId: Identifier | null;
  subcategoryId: Identifier | null;
}

export interface Health {
  status: string;
}

export type AssetType = "BANK_CASH" | "BROKERAGE_CASH" | "ETF" | "STOCK" | "FIXED_ASSET" | "OTHER";
export type ValuationSource = "MANUAL" | "TWELVE_DATA" | "YAHOO_FINANCE";
export type SupportedPortfolioCurrency = "EUR" | "USD" | "GBP" | "CHF";
export type FxProvenanceSource = "ECB" | "MANUAL" | "IDENTITY";

export interface QuoteConfiguration {
  symbol: string;
  exchange: string | null;
  micCode: string | null;
}

export interface ManualValuationInput {
  valuedAt: string;
  nativeValueMinor: number;
  unitPrice?: string | null;
  fxSource?: FxProvenanceSource | null;
  fxRateToEur?: string | null;
  fxRateDate?: string | null;
  fxPreviewToken?: string | null;
}

export interface Valuation {
  id: Identifier;
  assetId: Identifier;
  valuedAt: string;
  nativeValueMinor: number;
  eurValueMinor: number;
  quantity: string | null;
  unitPrice: string | null;
  costBasisNativeMinor: number | null;
  costBasisEurMinor: number | null;
  costBasisFxSource: string | null;
  costBasisFxRateToEur: string | null;
  costBasisFxRateDate: string | null;
  source: ValuationSource;
  quoteSymbol: string | null;
  quoteExchange: string | null;
  quoteMicCode: string | null;
  quoteName: string | null;
  quoteFetchedAt: string | null;
  quoteInterval: "LIVE" | "MONTHLY" | null;
  fxSource: string;
  fxRateToEur: string;
  fxRateDate: string;
  createdAt: string;
}

export interface Asset {
  id: Identifier;
  name: string;
  assetType: AssetType;
  currency: string;
  acquisitionDate: string;
  quantity: string | null;
  costBasisNativeMinor: number | null;
  costBasisEurMinor: number | null;
  costBasisFxSource: string | null;
  costBasisFxRateToEur: string | null;
  costBasisFxRateDate: string | null;
  quote: QuoteConfiguration | null;
  isActive: boolean;
  revision: number;
  createdAt: string;
  updatedAt: string;
  archivedAt: string | null;
  archivedOn: string | null;
  latestValuation: Valuation | null;
}

export interface AssetCreateInput {
  id?: Identifier;
  name: string;
  assetType: AssetType;
  currency: string;
  acquisitionDate: string;
  quantity?: string | null;
  costBasisNativeMinor?: number | null;
  costBasisEurMinor?: number | null;
  costBasisFxSource?: FxProvenanceSource | null;
  costBasisFxRateToEur?: string | null;
  costBasisFxRateDate?: string | null;
  costBasisFxPreviewToken?: string | null;
  quote?: QuoteConfiguration | null;
  initialValuation: ManualValuationInput;
}

export interface AssetPatchInput {
  expectedRevision: number;
  name?: string;
  assetType?: AssetType;
  quantity?: string | null;
  costBasisNativeMinor?: number | null;
  costBasisEurMinor?: number | null;
  costBasisFxSource?: FxProvenanceSource | null;
  costBasisFxRateToEur?: string | null;
  costBasisFxRateDate?: string | null;
  costBasisFxPreviewToken?: string | null;
  quote?: QuoteConfiguration | null;
  isActive?: boolean;
  effectiveAt?: string;
  replacementValuation?: ManualValuationInput;
}

export interface ManualValuationCreateInput extends ManualValuationInput {
  expectedRevision: number;
}

export interface AllocationItem {
  key: string;
  name: string;
  valueMinor: number;
  percentage: string | null;
}

export interface AssetPnl {
  assetId: Identifier;
  name: string;
  costBasisEurMinor: number | null;
  currentValueEurMinor: number | null;
  unrealizedPnlMinor: number | null;
  returnPercent: string | null;
}

export interface PortfolioHolding {
  assetId: Identifier;
  name: string;
  assetType: AssetType;
  currency: string;
  revision: number;
  quantity: string | null;
  valuationId: Identifier | null;
  valuedAt: string | null;
  source: ValuationSource | null;
  nativeValueMinor: number | null;
  eurValueMinor: number | null;
  costBasisEurMinor: number | null;
  unrealizedPnlMinor: number | null;
  returnPercent: string | null;
  missingValuation: boolean;
}

export interface PortfolioHistoryPoint {
  date: string;
  complete: boolean;
  knownValueMinor: number;
  totalValueMinor: number | null;
  trackedCostBasisMinor: number | null;
  unrealizedPnlMinor: number | null;
  pnlEligibleAssets: number;
  pnlCoveredAssets: number;
}

export interface Portfolio {
  asOf: string;
  generatedAt: string;
  currency: "EUR";
  complete: boolean;
  missingAssetIds: Identifier[];
  assetCount: number;
  valuedAssetCount: number;
  knownValueMinor: number;
  totalValueMinor: number | null;
  trackedCostBasisMinor: number | null;
  unrealizedPnlMinor: number | null;
  returnPercent: string | null;
  pnlEligibleAssets: number;
  pnlCoveredAssets: number;
  allocationByType: AllocationItem[];
  allocationByAsset: AllocationItem[];
  pnlByAsset: AssetPnl[];
  holdings: PortfolioHolding[];
  history: PortfolioHistoryPoint[];
}

export interface QuoteDetails {
  symbol: string;
  exchange: string | null;
  micCode: string | null;
  name: string;
  fetchedAt: string;
}

export interface FxDetails {
  source: "ECB" | "IDENTITY";
  rateToEur: string;
  rateDate: string;
}

export interface FxPreview {
  currency: string;
  valuedAt: string;
  source: "ECB" | "IDENTITY";
  rateToEur: string;
  rateDate: string;
  previewToken: string;
}

export interface QuotePreviewReady {
  status: "ready";
  assetId: Identifier;
  assetRevision: number;
  source: Exclude<ValuationSource, "MANUAL">;
  quoteInterval: "LIVE" | "MONTHLY";
  valuedAt: string;
  nativeCurrency: string;
  nativeValueMinor: number;
  eurValueMinor: number;
  quantity: string;
  unitPrice: string;
  quote: QuoteDetails;
  fx: FxDetails;
  previewToken: string;
}

export interface QuotePreviewError {
  status: "error";
  assetId: Identifier;
  assetRevision: number | null;
  error: { code: string; message: string; recoverable: boolean };
}

export type QuotePreviewItem = QuotePreviewReady | QuotePreviewError;

export interface QuoteHistoryPreview {
  assetId: Identifier;
  assetRevision: number;
  source: "YAHOO_FINANCE";
  availableMonths: number;
  existingMonths: number;
  firstDate: string | null;
  lastDate: string | null;
  items: QuotePreviewReady[];
}
