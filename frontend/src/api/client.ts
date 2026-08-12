import {
  mapCategories,
  mapCategory,
  mapCurrencies,
  mapDashboard,
  mapHealth,
  mapFxPreview,
  mapImportBatch,
  mapImportBatchPage,
  mapAsset,
  mapAssets,
  mapPortfolio,
  mapQuoteHistoryPreview,
  mapQuotePreview,
  mapReportPoints,
  mapReportSummary,
  mapSourceAccounts,
  mapStagedTransactionPage,
  mapStagedTransactions,
  mapSubcategory,
  mapTagRule,
  mapTagRules,
  mapTransaction,
  mapTransactionPage,
  mapValuation,
  mapValuations,
} from "./mappers";
import type {
  Asset,
  AssetCreateInput,
  AssetPatchInput,
  Category,
  Dashboard,
  DashboardQuery,
  FxPreview,
  Identifier,
  ImportBatch,
  ManualTransactionInput,
  ManualValuationCreateInput,
  Portfolio,
  QuoteHistoryPreview,
  QuotePreviewItem,
  QuotePreviewReady,
  ReportPoint,
  ReportQuery,
  ReportSummary,
  SourceAccount,
  StagedRowPatch,
  StagedTransaction,
  Subcategory,
  TagRule,
  Transaction,
  TransactionQuery,
  Valuation,
} from "./types";

interface ProblemBody {
  code?: string;
  message?: string;
  detail?: string | { msg?: string }[];
  field?: string;
  row?: number;
  recoverable?: boolean;
}

export class ApiProblem extends Error {
  readonly status: number;
  readonly code: string;
  readonly field?: string;
  readonly row?: number;
  readonly recoverable: boolean;

  constructor(status: number, body: ProblemBody) {
    const detail = Array.isArray(body.detail) ? body.detail.map((item) => item.msg).filter(Boolean).join("; ") : body.detail;
    super(body.message || detail || `Request failed with status ${status}`);
    this.name = "ApiProblem";
    this.status = status;
    this.code = body.code || `HTTP_${status}`;
    this.field = body.field;
    this.row = body.row;
    this.recoverable = body.recoverable ?? status >= 500;
  }
}

const API_ROOT = "/api/v1";

const snakePatch = (patch: StagedRowPatch) => ({
  id: patch.id,
  expected_revision: patch.expectedRevision,
  ...(patch.transactionDate !== undefined && { transaction_date: patch.transactionDate }),
  ...(patch.description !== undefined && { description: patch.description }),
  ...(patch.amountMinor !== undefined && { amount_minor: patch.amountMinor }),
  ...(patch.currency !== undefined && { currency: patch.currency }),
  ...(patch.categoryId !== undefined && { category_id: patch.categoryId }),
  ...(patch.subcategoryId !== undefined && { subcategory_id: patch.subcategoryId }),
  ...(patch.disposition !== undefined && { disposition: patch.disposition }),
  ...(patch.ignoreReason !== undefined && { ignore_reason: patch.ignoreReason }),
  ...(patch.rememberCorrection !== undefined && { remember_correction: patch.rememberCorrection }),
});

const reportQuery = ({ currency, dateFrom, dateTo }: ReportQuery) => ({
  currency,
  date_from: dateFrom,
  date_to: dateTo,
});

const safeMoneyMinor = (amount: number, field: string): number => {
  if (!Number.isSafeInteger(amount) || amount < 0) throw new ApiProblem(422, { code: "UNSAFE_MONEY_MINOR", message: `${field} must be a non-negative JavaScript safe integer.`, field, recoverable: true });
  return amount;
};

const safeNullableMoneyMinor = (amount: number | null | undefined, field: string): number | null =>
  amount == null ? null : safeMoneyMinor(amount, field);

const snakeValuation = (valuation: ManualValuationCreateInput | AssetCreateInput["initialValuation"]) => ({
  valued_at: valuation.valuedAt,
  native_value_minor: safeMoneyMinor(valuation.nativeValueMinor, "native_value_minor"),
  ...(valuation.unitPrice !== undefined && { unit_price: valuation.unitPrice }),
  ...(valuation.fxSource !== undefined && { fx_source: valuation.fxSource }),
  ...(valuation.fxRateToEur !== undefined && { fx_rate_to_eur: valuation.fxRateToEur }),
  ...(valuation.fxRateDate !== undefined && { fx_rate_date: valuation.fxRateDate }),
  ...(valuation.fxSource === "ECB" && valuation.fxPreviewToken && { fx_preview_token: valuation.fxPreviewToken }),
});

const snakeQuote = (quote: NonNullable<AssetCreateInput["quote"]>) => ({
  symbol: quote.symbol,
  exchange: quote.exchange,
  mic_code: quote.micCode,
});

const snakeReadyPreview = (item: QuotePreviewReady) => ({
  status: item.status,
  asset_id: item.assetId,
  asset_revision: item.assetRevision,
  source: item.source,
  quote_interval: item.quoteInterval,
  valued_at: item.valuedAt,
  native_currency: item.nativeCurrency,
  native_value_minor: safeMoneyMinor(item.nativeValueMinor, "native_value_minor"),
  eur_value_minor: safeMoneyMinor(item.eurValueMinor, "eur_value_minor"),
  quantity: item.quantity,
  unit_price: item.unitPrice,
  quote: {
    symbol: item.quote.symbol,
    exchange: item.quote.exchange,
    mic_code: item.quote.micCode,
    name: item.quote.name,
    fetched_at: item.quote.fetchedAt,
  },
  fx: { source: item.fx.source, rate_to_eur: item.fx.rateToEur, rate_date: item.fx.rateDate },
  preview_token: item.previewToken,
});

export class ApiClient {
  async health() {
    return this.request("/health", {}, mapHealth);
  }

  sourceAccounts = {
    list: (): Promise<SourceAccount[]> => this.request(`${API_ROOT}/source-accounts`, {}, mapSourceAccounts),
  };

  imports = {
    upload: (sourceAccountId: Identifier, file: File): Promise<ImportBatch> => {
      const form = new FormData();
      form.set("source_account_id", sourceAccountId);
      form.set("file", file);
      return this.request(`${API_ROOT}/imports`, { method: "POST", body: form }, mapImportBatch);
    },
    list: (): Promise<ImportBatch[]> =>
      this.collectPages(`${API_ROOT}/imports`, 200, mapImportBatchPage),
    detail: (id: Identifier): Promise<ImportBatch> => this.request(`${API_ROOT}/imports/${id}`, {}, mapImportBatch),
    rows: (id: Identifier): Promise<StagedTransaction[]> =>
      this.collectPages(`${API_ROOT}/imports/${id}/rows`, 500, mapStagedTransactionPage),
    patchRows: (id: Identifier, patches: StagedRowPatch[]): Promise<StagedTransaction[]> =>
      this.request(
        `${API_ROOT}/imports/${id}/rows`,
        { method: "PATCH", body: JSON.stringify({ rows: patches.map(snakePatch) }) },
        mapStagedTransactions,
      ),
    commit: (id: Identifier): Promise<ImportBatch> =>
      this.request(`${API_ROOT}/imports/${id}/commit`, { method: "POST" }, mapImportBatch),
    delete: (id: Identifier): Promise<void> => this.request(`${API_ROOT}/imports/${id}`, { method: "DELETE" }, () => undefined),
  };

  manualImports = {
    create: (rows: ManualTransactionInput[]): Promise<ImportBatch> =>
      this.createManualImport(rows),
  };

  private createManualImport(rows: ManualTransactionInput[]): Promise<ImportBatch> {
    const accountIds = new Set(rows.map((row) => row.sourceAccountId));
    if (accountIds.size !== 1) {
      throw new ApiProblem(422, {
        code: "MANUAL_IMPORT_ACCOUNT_MISMATCH",
        message: "A manual import batch must contain rows from one source account.",
        field: "source_account_id",
        recoverable: true,
      });
    }
    return this.request(
        `${API_ROOT}/manual-imports`,
        {
          method: "POST",
          body: JSON.stringify({
            source_account_id: rows[0]?.sourceAccountId,
            rows: rows.map((row) => ({
              transaction_date: row.date,
              description: row.description,
              amount_minor: row.amountMinor,
              currency: row.currency,
              category_id: row.categoryId,
              subcategory_id: row.subcategoryId,
            })),
          }),
        },
        mapImportBatch,
      );
  }

  transactions = {
    list: (query: TransactionQuery): Promise<ReturnType<typeof mapTransactionPage>> =>
      this.request(`${API_ROOT}/transactions${this.query({
        page: query.page,
        page_size: query.pageSize,
        currency: query.currency,
        date_from: query.dateFrom,
        date_to: query.dateTo,
        source_account_id: query.sourceAccountId,
        category_id: query.categoryId,
        search: query.search,
        include_excluded: query.includeExcluded,
      })}`, {}, mapTransactionPage),
    currencies: (): Promise<string[]> =>
      this.request(`${API_ROOT}/transactions/currencies`, {}, mapCurrencies),
    patch: (id: Identifier, patch: Partial<Transaction> & { expectedRevision: number }): Promise<Transaction> =>
      this.request(
        `${API_ROOT}/transactions/${id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            expected_revision: patch.expectedRevision,
            amount_minor: patch.amountMinor,
            category_id: patch.categoryId,
            subcategory_id: patch.subcategoryId,
            is_excluded: patch.excluded,
          }),
        },
        mapTransaction,
      ),
    delete: (id: Identifier, expectedRevision: number): Promise<void> =>
      this.request(
        `${API_ROOT}/transactions/${id}`,
        {
          method: "DELETE",
          body: JSON.stringify({
            expected_revision: expectedRevision,
            reason: "USER_DELETED",
          }),
        },
        () => undefined,
      ),
  };

  taxonomy = {
    categories: (): Promise<Category[]> => this.request(`${API_ROOT}/categories`, {}, mapCategories),
    createCategory: (name: string): Promise<Category> =>
      this.request(`${API_ROOT}/categories`, { method: "POST", body: JSON.stringify({ display_name: name }) }, mapCategory),
    patchCategory: (id: Identifier, patch: { name?: string; active?: boolean }): Promise<Category> =>
      this.request(`${API_ROOT}/categories/${id}`, { method: "PATCH", body: JSON.stringify({ display_name: patch.name, is_active: patch.active }) }, mapCategory),
    createSubcategory: (categoryId: Identifier, name: string): Promise<Subcategory> =>
      this.request(
        `${API_ROOT}/categories`,
        { method: "POST", body: JSON.stringify({ parent_category_id: categoryId, display_name: name }) },
        (input) => mapSubcategory(input, categoryId),
      ),
    patchSubcategory: (id: Identifier, patch: { name?: string; active?: boolean }): Promise<Subcategory> =>
      this.request(`${API_ROOT}/categories/${id}`, { method: "PATCH", body: JSON.stringify({ display_name: patch.name, is_active: patch.active }) }, mapSubcategory),
  };

  tagRules = {
    list: (): Promise<TagRule[]> => this.collectPages(`${API_ROOT}/tag-rules`, 200, (input) => {
      const root = input as { page?: number; page_size?: number; total?: number };
      const items = mapTagRules(input);
      return { items, page: root.page ?? 1, pageSize: root.page_size ?? 200, total: root.total ?? items.length };
    }),
    create: (rule: Omit<TagRule, "id" | "active">): Promise<TagRule> =>
      this.request(
        `${API_ROOT}/tag-rules`,
        {
          method: "POST",
          body: JSON.stringify({
            description: rule.match,
            scope: rule.scope,
            provider: rule.provider,
            source_account_id: rule.sourceAccountId,
            category_id: rule.categoryId,
            subcategory_id: rule.subcategoryId,
          }),
        },
        mapTagRule,
      ),
    patch: (id: Identifier, patch: { active: boolean }): Promise<TagRule> =>
      this.request(
        `${API_ROOT}/tag-rules/${id}`,
        { method: "PATCH", body: JSON.stringify({ is_enabled: patch.active }) },
        mapTagRule,
      ),
  };

  reports = {
    summary: (query: ReportQuery): Promise<ReportSummary> =>
      this.request(`${API_ROOT}/reports/summary${this.query(reportQuery(query))}`, {}, mapReportSummary),
    trend: (query: ReportQuery): Promise<ReportPoint[]> =>
      this.request(`${API_ROOT}/reports/trend${this.query(reportQuery(query))}`, {}, mapReportPoints),
    categories: (query: ReportQuery): Promise<ReportPoint[]> =>
      this.request(`${API_ROOT}/reports/categories${this.query(reportQuery(query))}`, {}, mapReportPoints),
    accounts: (query: ReportQuery): Promise<ReportPoint[]> =>
      this.request(`${API_ROOT}/reports/accounts${this.query(reportQuery(query))}`, {}, mapReportPoints),
    recent: (query: ReportQuery): Promise<Transaction[]> =>
      this.request(`${API_ROOT}/reports/recent${this.query(reportQuery(query))}`, {}, (input) => {
        if (Array.isArray(input)) return input.map(mapTransaction);
        return mapTransactionPage(input).items;
      }),
  };

  dashboard = {
    get: (query: DashboardQuery): Promise<Dashboard> => {
      const params = new URLSearchParams({ date_from: query.dateFrom, date_to: query.dateTo });
      query.categoryIds?.forEach((id) => params.append("category_id", id));
      query.subcategoryIds?.forEach((id) => params.append("subcategory_id", id));
      return this.request(`${API_ROOT}/dashboard?${params.toString()}`, {}, mapDashboard);
    },
  };

  assets = {
    list: (includeArchived = false): Promise<Asset[]> =>
      this.request(`${API_ROOT}/assets${this.query({ include_archived: includeArchived || undefined })}`, {}, mapAssets),
    detail: (id: Identifier): Promise<Asset> => this.request(`${API_ROOT}/assets/${id}`, {}, mapAsset),
    create: (input: AssetCreateInput): Promise<Asset> => this.request(`${API_ROOT}/assets`, {
      method: "POST",
      body: JSON.stringify({
        ...(input.id && { id: input.id }),
        name: input.name,
        asset_type: input.assetType,
        currency: input.currency,
        acquisition_date: input.acquisitionDate,
        quantity: input.quantity ?? null,
        cost_basis_native_minor: safeNullableMoneyMinor(input.costBasisNativeMinor, "cost_basis_native_minor"),
        cost_basis_eur_minor: safeNullableMoneyMinor(input.costBasisEurMinor, "cost_basis_eur_minor"),
        cost_basis_fx_source: input.costBasisFxSource ?? null,
        cost_basis_fx_rate_to_eur: input.costBasisFxRateToEur ?? null,
        cost_basis_fx_rate_date: input.costBasisFxRateDate ?? null,
        ...(input.costBasisFxSource === "ECB" && input.costBasisFxPreviewToken && { cost_basis_fx_preview_token: input.costBasisFxPreviewToken }),
        quote: input.quote ? snakeQuote(input.quote) : null,
        initial_valuation: snakeValuation(input.initialValuation),
      }),
    }, mapAsset),
    patch: (id: Identifier, input: AssetPatchInput): Promise<Asset> => this.request(`${API_ROOT}/assets/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        expected_revision: input.expectedRevision,
        ...(input.name !== undefined && { name: input.name }),
        ...(input.assetType !== undefined && { asset_type: input.assetType }),
        ...(input.quantity !== undefined && { quantity: input.quantity }),
        ...(input.costBasisNativeMinor !== undefined && { cost_basis_native_minor: safeNullableMoneyMinor(input.costBasisNativeMinor, "cost_basis_native_minor") }),
        ...(input.costBasisEurMinor !== undefined && { cost_basis_eur_minor: safeNullableMoneyMinor(input.costBasisEurMinor, "cost_basis_eur_minor") }),
        ...(input.costBasisFxSource !== undefined && { cost_basis_fx_source: input.costBasisFxSource }),
        ...(input.costBasisFxRateToEur !== undefined && { cost_basis_fx_rate_to_eur: input.costBasisFxRateToEur }),
        ...(input.costBasisFxRateDate !== undefined && { cost_basis_fx_rate_date: input.costBasisFxRateDate }),
        ...(input.costBasisFxSource === "ECB" && input.costBasisFxPreviewToken && { cost_basis_fx_preview_token: input.costBasisFxPreviewToken }),
        ...(input.quote !== undefined && { quote: input.quote ? snakeQuote(input.quote) : null }),
        ...(input.isActive !== undefined && { is_active: input.isActive }),
        ...(input.effectiveAt !== undefined && { effective_at: input.effectiveAt }),
        ...(input.replacementValuation !== undefined && { replacement_valuation: snakeValuation(input.replacementValuation) }),
      }),
    }, mapAsset),
    valuations: (id: Identifier): Promise<Valuation[]> => this.request(`${API_ROOT}/assets/${id}/valuations`, {}, mapValuations),
    addValuation: (id: Identifier, input: ManualValuationCreateInput): Promise<Valuation> => this.request(`${API_ROOT}/assets/${id}/valuations`, {
      method: "POST",
      body: JSON.stringify({ expected_revision: input.expectedRevision, ...snakeValuation(input) }),
    }, mapValuation),
  };

  portfolio = {
    get: (asOf?: string): Promise<Portfolio> => this.request(`${API_ROOT}/portfolio${this.query({ as_of: asOf })}`, {}, mapPortfolio),
    previewFx: (currency: string, valuedAt: string): Promise<FxPreview> =>
      this.request(`${API_ROOT}/portfolio/fx-preview${this.query({ currency, valued_at: valuedAt })}`, {}, mapFxPreview),
    previewQuotes: (assetIds: Identifier[]): Promise<QuotePreviewItem[]> => {
      const params = new URLSearchParams();
      assetIds.forEach((id) => params.append("asset_id", id));
      return this.request(`${API_ROOT}/portfolio/quote-preview?${params.toString()}`, {}, mapQuotePreview);
    },
    previewQuoteHistory: (assetId: Identifier): Promise<QuoteHistoryPreview> =>
      this.request(`${API_ROOT}/portfolio/history-preview?asset_id=${encodeURIComponent(assetId)}`, {}, mapQuoteHistoryPreview),
    saveQuoteSnapshots: (items: QuotePreviewReady[]): Promise<Valuation[]> =>
      this.request(`${API_ROOT}/portfolio/quote-snapshots`, {
        method: "POST",
        body: JSON.stringify({ items: items.map(snakeReadyPreview) }),
      }, (input) => mapValuations((input as { items?: unknown }).items)),
  };

  private query(values: Record<string, unknown>): string {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(values)) {
      if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
    }
    const query = params.toString();
    return query ? `?${query}` : "";
  }

  private async collectPages<T>(
    path: string,
    pageSize: number,
    mapPage: (input: unknown) => { items: T[]; page: number; pageSize: number; total: number },
  ): Promise<T[]> {
    const items: T[] = [];
    let page = 1;
    while (true) {
      const result = await this.request(
        `${path}${this.query({ page, page_size: pageSize })}`,
        {},
        mapPage,
      );
      items.push(...result.items);
      if (items.length >= result.total || result.items.length === 0) return items;
      page += 1;
    }
  }

  private async request<T>(path: string, init: RequestInit, map: (input: unknown) => T): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
    headers.set("Accept", "application/json");
    let response: Response;
    try {
      response = await fetch(path, { ...init, headers });
    } catch {
      throw new ApiProblem(0, {
        code: "NETWORK_ERROR",
        message: "The ledger service could not be reached. Check that it is running, then retry.",
        recoverable: true,
      });
    }
    const body = response.status === 204 ? undefined : await response.json().catch(() => undefined);
    if (!response.ok) throw new ApiProblem(response.status, (body ?? {}) as ProblemBody);
    return map(body);
  }
}

export const api = new ApiClient();
