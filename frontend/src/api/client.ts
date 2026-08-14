import {
  mapCategories,
  mapCategory,
  mapCurrencies,
  mapDashboard,
  mapHealth,
  mapFxPreview,
  mapImportBatch,
  mapImportBatchPage,
  mapImportInspection,
  mapImportMappingTemplate,
  mapImportMappingTemplates,
  mapMappingPreview,
  mapMappingConfirmation,
  mapMappingSuggestionPayload,
  mapMappingSuggestion,
  mapAsset,
  mapAssets,
  mapPortfolio,
  mapQuoteHistoryPreview,
  mapQuotePreview,
  mapReportPoints,
  mapReportSummary,
  mapAccount,
  mapAccounts,
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
  ImportExecutionPlan,
  ImportInspection,
  ImportMappingTemplate,
  MappingPreview,
  MappingConfirmation,
  MappingSuggestionPayload,
  MappingSuggestion,
  ManualTransactionInput,
  ManualValuationCreateInput,
  Portfolio,
  QuoteHistoryPreview,
  QuotePreviewItem,
  QuotePreviewReady,
  ReportPoint,
  ReportQuery,
  ReportSummary,
  Account,
  AccountCreateInput,
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

const snakeNumberFormat = (format: ImportExecutionPlan["amount"]["numberFormat"]) => ({
  decimal_separator: format.decimalSeparator,
  thousands_separator: format.thousandsSeparator,
  strip_currency_symbols: format.stripCurrencySymbols,
  allow_parentheses: format.allowParentheses,
  allow_trailing_minus: format.allowTrailingMinus,
});

const snakeExecutionPlan = (plan: ImportExecutionPlan): Record<string, unknown> => {
  return {
    plan_type: "universal", schema_version: plan.schemaVersion,
    transaction_date: plan.transactionDate ? { source_column: plan.transactionDate.sourceColumn, format: plan.transactionDate.format } : null,
    transaction_timestamp: plan.transactionTimestamp ? { source_column: plan.transactionTimestamp.sourceColumn, format: plan.transactionTimestamp.format, timezone: plan.transactionTimestamp.timezone } : null,
    description: { source_column: plan.description.sourceColumn, strip: plan.description.strip, collapse_whitespace: plan.description.collapseWhitespace },
    amount: plan.amount.kind === "signed"
      ? { kind: "signed", source_column: plan.amount.sourceColumn, number_format: snakeNumberFormat(plan.amount.numberFormat), expense_sign_convention: plan.amount.signConvention }
      : { kind: "debit_credit", debit_column: plan.amount.debitColumn, credit_column: plan.amount.creditColumn, number_format: snakeNumberFormat(plan.amount.numberFormat), debit_source_sign: plan.amount.debitSourceSign, credit_source_sign: plan.amount.creditSourceSign },
    currency: plan.currency.kind === "source" ? { kind: "source", source_column: plan.currency.sourceColumn } : { kind: "constant", value: plan.currency.value },
    source_native_id: plan.sourceNativeId ? { source_column: plan.sourceNativeId.sourceColumn } : null,
    category_hint: plan.categoryHint ? { source_column: plan.categoryHint.sourceColumn } : null,
    subcategory_hint: plan.subcategoryHint ? { source_column: plan.subcategoryHint.sourceColumn } : null,
    row_bounds: { first_row: plan.rowBounds.firstRow, last_row: plan.rowBounds.lastRow },
    exact_filters: plan.exactFilters.map((filter) => ({ source_column: filter.sourceColumn, mode: filter.mode, values: filter.values })),
    skip_empty_rows: plan.skipEmptyRows, skip_repeated_headers: plan.skipRepeatedHeaders,
    footer_rule: plan.footerRule ? { source_column: plan.footerRule.sourceColumn, normalized_value: plan.footerRule.normalizedValue } : null,
  };
};

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

  accounts = {
    list: (): Promise<Account[]> => this.request(`${API_ROOT}/accounts`, {}, mapAccounts),
    create: (input: AccountCreateInput): Promise<Account> => this.request(`${API_ROOT}/accounts`, {
      method: "POST",
      body: JSON.stringify({ name: input.name, default_currency: input.defaultCurrency }),
    }, mapAccount),
    patch: (id: Identifier, input: { name?: string; active?: boolean }): Promise<Account> => this.request(`${API_ROOT}/accounts/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ ...(input.name !== undefined && { name: input.name }), ...(input.active !== undefined && { is_active: input.active }) }),
    }, mapAccount),
  };

  imports = {
    upload: (accountId: Identifier, file: File): Promise<ImportBatch> => {
      const form = new FormData();
      form.set("account_id", accountId);
      form.set("file", file);
      return this.request(`${API_ROOT}/imports`, { method: "POST", body: form }, mapImportBatch);
    },
    list: (): Promise<ImportBatch[]> =>
      this.collectPages(`${API_ROOT}/imports`, 200, mapImportBatchPage),
    detail: (id: Identifier): Promise<ImportBatch> => this.request(`${API_ROOT}/imports/${id}`, {}, mapImportBatch),
    inspection: (id: Identifier, pagination: { offset?: number; limit?: number } = {}): Promise<ImportInspection> => this.request(`${API_ROOT}/imports/${id}/inspection${this.query(pagination)}`, {}, mapImportInspection),
    patchInspection: (id: Identifier, patch: { expectedRevision: number; selectedSheet: string; headerRow: number; previewOffset?: number; previewLimit?: number; confirmRestaging?: boolean }): Promise<ImportInspection> =>
      this.request(`${API_ROOT}/imports/${id}/inspection${this.query({ offset: patch.previewOffset, limit: patch.previewLimit })}`, { method: "PATCH", body: JSON.stringify({ expected_revision: patch.expectedRevision, selected_sheet: patch.selectedSheet, header_row: patch.headerRow, confirm_restaging: patch.confirmRestaging ?? false }) }, mapImportInspection),
    sourceFileUrl: (id: Identifier): string => `${API_ROOT}/imports/${id}/source-file`,
    mappingSuggestionPayload: (id: Identifier): Promise<MappingSuggestionPayload> => this.request(`${API_ROOT}/imports/${id}/mapping-suggestion-payload`, {}, mapMappingSuggestionPayload),
    suggestMapping: (id: Identifier, input: { expectedRevision: number; digest: string; consent: true }): Promise<MappingSuggestion> =>
      this.request(`${API_ROOT}/imports/${id}/mapping-suggestion`, { method: "POST", body: JSON.stringify({ expected_revision: input.expectedRevision, payload_sha256: input.digest, consent: input.consent }) }, mapMappingSuggestion),
    previewMapping: (id: Identifier, plan: ImportExecutionPlan, pagination: { offset?: number; limit?: number } = {}): Promise<MappingPreview> =>
      this.request(`${API_ROOT}/imports/${id}/mapping-preview`, { method: "POST", body: JSON.stringify({ execution_plan: snakeExecutionPlan(plan), offset: pagination.offset ?? 0, limit: pagination.limit ?? 25 }) }, mapMappingPreview),
    confirmMapping: (id: Identifier, input: { plan: ImportExecutionPlan; expectedRevision: number; templateId?: string | null; templateVersionId?: string | null; confirmRestaging?: boolean }): Promise<MappingConfirmation> =>
      this.request(`${API_ROOT}/imports/${id}/mapping`, { method: "PUT", body: JSON.stringify({ expected_revision: input.expectedRevision, execution_plan: snakeExecutionPlan(input.plan), source_template_id: input.templateId ?? null, source_template_version_id: input.templateVersionId ?? null, confirm_restaging: input.confirmRestaging ?? false }) }, mapMappingConfirmation),
    stage: (id: Identifier, expectedRevision: number, expectedMappingRevision: number): Promise<ImportBatch> =>
      this.request(`${API_ROOT}/imports/${id}/stage`, { method: "POST", body: JSON.stringify({ expected_revision: expectedRevision, expected_mapping_revision: expectedMappingRevision }) }, mapImportBatch),
    rows: (id: Identifier): Promise<StagedTransaction[]> =>
      this.collectPages(`${API_ROOT}/imports/${id}/rows`, 500, mapStagedTransactionPage),
    patchRows: (id: Identifier, expectedRevision: number, patches: StagedRowPatch[]): Promise<StagedTransaction[]> =>
      this.request(
        `${API_ROOT}/imports/${id}/rows`,
        { method: "PATCH", body: JSON.stringify({ expected_revision: expectedRevision, rows: patches.map(snakePatch) }) },
        mapStagedTransactions,
      ),
    commit: (id: Identifier, expectedRevision: number): Promise<ImportBatch> =>
      this.request(`${API_ROOT}/imports/${id}/commit`, { method: "POST", body: JSON.stringify({ expected_revision: expectedRevision }) }, mapImportBatch),
    delete: (id: Identifier, expectedRevision: number): Promise<void> => this.request(`${API_ROOT}/imports/${id}`, { method: "DELETE", body: JSON.stringify({ expected_revision: expectedRevision }) }, () => undefined),
  };

  importMappings = {
    list: (query: { accountId?: Identifier; structuralSignature?: string; includeInactive?: boolean } = {}): Promise<ImportMappingTemplate[]> => this.request(`${API_ROOT}/import-mappings${this.query({ account_id: query.accountId, structural_signature: query.structuralSignature, include_inactive: query.includeInactive || undefined })}`, {}, mapImportMappingTemplates),
    detail: (id: Identifier): Promise<ImportMappingTemplate> => this.request(`${API_ROOT}/import-mappings/${id}`, {}, mapImportMappingTemplate),
    create: (input: { name: string; structuralSignature: string; accountId: Identifier | null; plan: ImportExecutionPlan; sourceBatchId?: Identifier; sourceBatchRevision?: number }): Promise<ImportMappingTemplate> =>
      this.request(`${API_ROOT}/import-mappings`, { method: "POST", body: JSON.stringify({ name: input.name, structural_signature: input.structuralSignature, account_id: input.accountId, execution_plan: snakeExecutionPlan(input.plan), source_batch_id: input.sourceBatchId, source_batch_revision: input.sourceBatchRevision }) }, mapImportMappingTemplate),
    patch: (id: Identifier, input: { expectedRevision: number; name?: string; active?: boolean; plan?: ImportExecutionPlan }): Promise<ImportMappingTemplate> =>
      this.request(`${API_ROOT}/import-mappings/${id}`, { method: "PATCH", body: JSON.stringify({ expected_revision: input.expectedRevision, ...(input.name !== undefined && { name: input.name }), ...(input.active !== undefined && { is_active: input.active }), ...(input.plan && { execution_plan: snakeExecutionPlan(input.plan) }) }) }, mapImportMappingTemplate),
  };

  manualImports = {
    create: (rows: ManualTransactionInput[]): Promise<ImportBatch> =>
      this.createManualImport(rows),
  };

  private createManualImport(rows: ManualTransactionInput[]): Promise<ImportBatch> {
    const accountIds = new Set(rows.map((row) => row.accountId));
    if (accountIds.size !== 1) {
      throw new ApiProblem(422, {
        code: "MANUAL_IMPORT_ACCOUNT_MISMATCH",
        message: "A manual import batch must contain rows from one source account.",
        field: "account_id",
        recoverable: true,
      });
    }
    return this.request(
        `${API_ROOT}/manual-imports`,
        {
          method: "POST",
          body: JSON.stringify({
            account_id: rows[0]?.accountId,
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
        account_id: query.accountId,
        category_id: query.categoryId,
        search: query.search,
        sort_by: query.sortBy,
        sort_direction: query.sortDirection,
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
            account_id: rule.accountId,
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
