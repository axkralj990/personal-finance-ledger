import { ApiClient } from "./client";
import type { ManualTransactionInput } from "./types";

const batchResponse = {
  id: "batch-1",
  account_id: "manual-account",
  original_filename: "manual-entry",
  status: "READY",
  total_rows: 1,
  valid_rows: 1,
  needs_review_rows: 0,
  duplicate_rows: 0,
  included_rows: 0,
  ignored_rows: 0,
  errors: [],
  created_at: "2026-08-09T10:00:00Z",
  updated_at: "2026-08-09T10:00:00Z",
};

const stagedRow = (rowNumber: number) => ({
  id: `row-${rowNumber}`,
  row_number: rowNumber,
  revision: 1,
  raw_json: { row: rowNumber },
  transaction_date: "2026-08-09",
  description: `Row ${rowNumber}`,
  amount_minor: -100,
  currency: "EUR",
  kind: "EXPENSE",
  category_id: null,
  subcategory_id: null,
  predicted_category_id: null,
  predicted_subcategory_id: null,
  prediction_confidence: null,
  validation_issues: [],
  duplicate_status: "NONE",
  duplicate_candidate_id: null,
  duplicate_candidate: null,
  duplicate_explanation: null,
  disposition: "PENDING",
  ignore_reason: null,
  remember_correction: false,
});

describe("ApiClient contract requests", () => {
  it("uses the generic accounts API without provider fields", async () => {
    const responses: unknown[] = [
      [
        {
          id: "unknown",
          name: "Unknown",
          default_currency: "EUR",
          is_active: true,
        },
      ],
      { id: "cash", name: "Cash", default_currency: "USD", is_active: true },
      { id: "cash", name: "Wallet", default_currency: "USD", is_active: false },
    ];
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        void init;
        return new Response(JSON.stringify(responses.shift()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient();

    await expect(client.accounts.list()).resolves.toEqual([
      { id: "unknown", name: "Unknown", defaultCurrency: "EUR", active: true },
    ]);
    await client.accounts.create({ name: "Cash", defaultCurrency: "USD" });
    await client.accounts.patch("cash", { name: "Wallet", active: false });

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/accounts",
      "/api/v1/accounts",
      "/api/v1/accounts/cash",
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      name: "Cash",
      default_currency: "USD",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toEqual({
      name: "Wallet",
      is_active: false,
    });
    expect(String(fetchMock.mock.calls[1]?.[1]?.body)).not.toContain(
      "provider",
    );
  });

  it("uses revision-protected snake_case universal import endpoints", async () => {
    const responses: unknown[] = [
      { valid_rows: 1, error_rows: 0, filtered_rows: 0, rows: [] },
      null,
      {
        id: "batch-1",
        account_id: "account-1",
        original_filename: "table.csv",
        status: "STAGING",
        revision: 5,
      },
    ];
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        void init;
        return new Response(JSON.stringify(responses.shift()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient();
    const plan = {
      planType: "universal" as const,
      schemaVersion: "universal-v1",
      transactionDate: { sourceColumn: "c000", format: "%d/%m/%Y" },
      transactionTimestamp: {
        sourceColumn: "c004",
        format: "%Y-%m-%dT%H:%M:%S%z",
        timezone: "Europe/Ljubljana",
      },
      description: {
        sourceColumn: "c001",
        strip: true,
        collapseWhitespace: true,
      },
      amount: {
        kind: "signed" as const,
        sourceColumn: "c002",
        numberFormat: {
          decimalSeparator: "." as const,
          thousandsSeparator: ",",
          stripCurrencySymbols: true,
          allowParentheses: false,
          allowTrailingMinus: false,
        },
        signConvention: "EXPENSES_POSITIVE" as const,
      },
      currency: { kind: "constant" as const, value: "EUR" },
      sourceNativeId: null,
      categoryHint: null,
      subcategoryHint: null,
      rowBounds: { firstRow: null, lastRow: null },
      exactFilters: [],
      skipEmptyRows: true,
      skipRepeatedHeaders: true,
      footerRule: null,
    };
    responses[1] = {
      batch_id: "batch-1",
      revision: 4,
      mapping_revision: 2,
      execution_plan: {
        plan_type: "universal",
        schema_version: "universal-v1",
        transaction_date: {
          source_column: "c000",
          format: "%d/%m/%Y",
        },
        transaction_timestamp: {
          source_column: "c004",
          format: "%Y-%m-%dT%H:%M:%S%z",
          timezone: "Europe/Ljubljana",
        },
        description: {
          source_column: "c001",
          strip: true,
          collapse_whitespace: true,
        },
        amount: {
          kind: "signed",
          source_column: "c002",
          number_format: {
            decimal_separator: ".",
            thousands_separator: ",",
            strip_currency_symbols: true,
            allow_parentheses: false,
            allow_trailing_minus: false,
          },
          expense_sign_convention: "EXPENSES_POSITIVE",
        },
        currency: { kind: "constant", value: "EUR" },
        source_native_id: null,
        category_hint: null,
        subcategory_hint: null,
        row_bounds: { first_row: null, last_row: null },
        exact_filters: [],
        skip_empty_rows: true,
        skip_repeated_headers: true,
        footer_rule: null,
      },
    };
    await client.imports.previewMapping("batch-1", plan);
    const confirmation = await client.imports.confirmMapping("batch-1", {
      plan,
      expectedRevision: 3,
      templateId: "template-1",
      templateVersionId: "version-2",
    });
    await client.imports.stage("batch-1", 4, 2);
    expect(confirmation.plan.transactionTimestamp).toEqual({
      sourceColumn: "c004",
      format: "%Y-%m-%dT%H:%M:%S%z",
      timezone: "Europe/Ljubljana",
    });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/imports/batch-1/mapping-preview",
      "/api/v1/imports/batch-1/mapping",
      "/api/v1/imports/batch-1/stage",
    ]);
    const previewRequest = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(previewRequest).toMatchObject({
      execution_plan: {
        plan_type: "universal",
        transaction_date: {
          source_column: "c000",
          format: "%d/%m/%Y",
        },
        transaction_timestamp: {
          source_column: "c004",
          format: "%Y-%m-%dT%H:%M:%S%z",
          timezone: "Europe/Ljubljana",
        },
        amount: {
          expense_sign_convention: "EXPENSES_POSITIVE",
          number_format: { thousands_separator: "," },
        },
      },
    });
    expect(previewRequest.execution_plan.transaction_date).not.toHaveProperty("day_first");
    expect(previewRequest.execution_plan.transaction_timestamp).not.toHaveProperty("day_first");
    expect(Object.keys(previewRequest.execution_plan.amount)).toEqual([
      "kind",
      "source_column",
      "number_format",
      "expense_sign_convention",
    ]);
    expect(previewRequest).not.toHaveProperty("expected_revision");
    expect(
      JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body)),
    ).toMatchObject({
      expected_revision: 3,
      source_template_id: "template-1",
      source_template_version_id: "version-2",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toEqual({
      expected_revision: 4,
      expected_mapping_revision: 2,
    });
  });

  it("sends one top-level account for manual rows", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        void init;
        return new Response(JSON.stringify(batchResponse), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const input: ManualTransactionInput = {
      accountId: "manual-account",
      date: "2026-08-09",
      description: "Cafe",
      amountMinor: -450,
      currency: "EUR",
      categoryId: null,
      subcategoryId: null,
    };

    await new ApiClient().manualImports.create([input]);

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/v1/manual-imports");
    expect(JSON.parse(String(init?.body))).toEqual({
      account_id: "manual-account",
      rows: [
        {
          transaction_date: "2026-08-09",
          description: "Cafe",
          amount_minor: -450,
          currency: "EUR",
          category_id: null,
          subcategory_id: null,
        },
      ],
    });
  });

  it("collects every bounded staged-row page", async () => {
    const firstPage = Array.from({ length: 500 }, (_, index) =>
      stagedRow(index + 1),
    );
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes("page=2")
        ? { items: [stagedRow(501)], page: 2, page_size: 500, total: 501 }
        : { items: firstPage, page: 1, page_size: 500, total: 501 };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const rows = await new ApiClient().imports.rows("batch-1");

    expect(rows).toHaveLength(501);
    expect(rows[500]?.rowNumber).toBe(501);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "/api/v1/imports/batch-1/rows?page=2&page_size=500",
    );
  });

  it("serializes nullable staged repair fields with snake-case names", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        void init;
        return new Response(JSON.stringify([stagedRow(1)]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    await new ApiClient().imports.patchRows("batch-1", 9, [
      {
        id: "row-1",
        expectedRevision: 2,
        transactionDate: "2026-08-08",
        description: "Repaired",
        amountMinor: null,
        currency: "SGD",
      },
    ]);

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      expected_revision: 9,
      rows: [
        {
          id: "row-1",
          expected_revision: 2,
          transaction_date: "2026-08-08",
          description: "Repaired",
          amount_minor: null,
          currency: "SGD",
        },
      ],
    });
  });

  it("serializes transaction search and sorting", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        void init;
        return new Response(
          JSON.stringify({ items: [], page: 1, page_size: 25, total: 0 }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        );
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    await new ApiClient().transactions.list({
      search: "Synthetic cafe",
      sortBy: "amount",
      sortDirection: "asc",
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/transactions?search=Synthetic+cafe&sort_by=amount&sort_direction=asc",
    );
  });

  it("serializes signed transaction amount corrections", async () => {
    const response = {
      id: "transaction-1",
      revision: 5,
      transaction_date: "2026-08-10",
      description: "Synthetic cafe",
      amount_minor: -1999,
      currency: "EUR",
      kind: "EXPENSE",
      account_id: "account-1",
      account_name: "Manual EUR",
      category_id: null,
      category_name: null,
      subcategory_id: null,
      subcategory_name: null,
      import_batch_id: "batch-1",
    };
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        void init;
        return new Response(JSON.stringify(response), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    await new ApiClient().transactions.patch("transaction-1", {
      expectedRevision: 4,
      amountMinor: -1999,
    });

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      expected_revision: 4,
      amount_minor: -1999,
    });
  });

  it("deletes a transaction with revision protection", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        void init;
        return new Response(null, { status: 204 });
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    await new ApiClient().transactions.delete("transaction-1", 4);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/transactions/transaction-1",
    );
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("DELETE");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      expected_revision: 4,
      reason: "USER_DELETED",
    });
  });

  it("preserves account scope when creating and toggling tag rules", async () => {
    const response = {
      id: "rule-1",
      description: "COFFEE",
      scope: "ACCOUNT",
      account_id: "account-1",
      category_id: "food",
      subcategory_id: null,
      is_enabled: true,
    };
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        void init;
        return new Response(JSON.stringify(response), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient();

    await client.tagRules.create({
      match: "COFFEE",
      scope: "ACCOUNT",
      accountId: "account-1",
      categoryId: "food",
      subcategoryId: null,
    });
    await client.tagRules.patch("rule-1", { active: false });

    expect(
      JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)),
    ).toMatchObject({ account_id: "account-1", scope: "ACCOUNT" });
    expect(
      JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)),
    ).not.toHaveProperty("provider");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/tag-rules/rule-1");
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      is_enabled: false,
    });
  });

  it("serializes asset creation with initial valuation in exact snake_case", async () => {
    const response = {
      id: "asset-1",
      name: "World ETF",
      asset_type: "ETF",
      currency: "USD",
      acquisition_date: "2026-01-01",
      quantity: "2.5",
      cost_basis_native_minor: 10000,
      cost_basis_eur_minor: 9200,
      quote: { symbol: "VWCE", exchange: "XETRA", mic_code: "XETR" },
      is_active: true,
      revision: 1,
    };
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        void init;
        return new Response(JSON.stringify(response), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    await new ApiClient().assets.create({
      name: "World ETF",
      assetType: "ETF",
      currency: "USD",
      acquisitionDate: "2026-01-01",
      quantity: "2.5",
      costBasisNativeMinor: 10000,
      costBasisEurMinor: 9200,
      costBasisFxSource: "ECB",
      costBasisFxRateToEur: "0.92",
      costBasisFxRateDate: "2025-12-31",
      costBasisFxPreviewToken: "d".repeat(64),
      quote: { symbol: "VWCE", exchange: "XETRA", micCode: "XETR" },
      initialValuation: {
        valuedAt: "2026-08-11",
        nativeValueMinor: 12500,
        unitPrice: "50",
        fxSource: "ECB",
        fxRateToEur: "0.92",
        fxRateDate: "2026-08-10",
        fxPreviewToken: "e".repeat(64),
      },
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/assets");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      name: "World ETF",
      asset_type: "ETF",
      currency: "USD",
      acquisition_date: "2026-01-01",
      quantity: "2.5",
      cost_basis_native_minor: 10000,
      cost_basis_eur_minor: 9200,
      cost_basis_fx_source: "ECB",
      cost_basis_fx_rate_to_eur: "0.92",
      cost_basis_fx_rate_date: "2025-12-31",
      cost_basis_fx_preview_token: "d".repeat(64),
      quote: { symbol: "VWCE", exchange: "XETRA", mic_code: "XETR" },
      initial_valuation: {
        valued_at: "2026-08-11",
        native_value_minor: 12500,
        unit_price: "50",
        fx_source: "ECB",
        fx_rate_to_eur: "0.92",
        fx_rate_date: "2026-08-10",
        fx_preview_token: "e".repeat(64),
      },
    });
  });

  it("serializes manual valuations and revision-protected archive", async () => {
    const valuation = {
      id: "v-2",
      asset_id: "asset-1",
      valued_at: "2026-07-31",
      native_value_minor: 11000,
      eur_value_minor: 10120,
      source: "MANUAL",
      fx_source: "MANUAL",
      fx_rate_to_eur: "0.92",
      fx_rate_date: "2026-07-31",
    };
    const asset = {
      id: "asset-1",
      name: "World ETF",
      asset_type: "ETF",
      currency: "USD",
      acquisition_date: "2026-01-01",
      is_active: false,
      revision: 4,
    };
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void init;
        return new Response(
          JSON.stringify(
            String(input).endsWith("valuations") ? valuation : asset,
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient();
    await client.assets.addValuation("asset-1", {
      expectedRevision: 3,
      valuedAt: "2026-07-31",
      nativeValueMinor: 11000,
      fxSource: "MANUAL",
      fxRateToEur: "0.92",
      fxRateDate: "2026-07-31",
      fxPreviewToken: "x".repeat(64),
    });
    await client.assets.patch("asset-1", {
      expectedRevision: 3,
      isActive: false,
    });
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      expected_revision: 3,
      valued_at: "2026-07-31",
      native_value_minor: 11000,
      fx_source: "MANUAL",
      fx_rate_to_eur: "0.92",
      fx_rate_date: "2026-07-31",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      expected_revision: 3,
      is_active: false,
    });
  });

  it("uses repeated preview ids and persists ready previews unchanged", async () => {
    const preview = {
      status: "ready",
      asset_id: "asset-1",
      asset_revision: 2,
      source: "TWELVE_DATA",
      quote_interval: "LIVE",
      valued_at: "2026-08-11",
      native_currency: "EUR",
      native_value_minor: 12000,
      eur_value_minor: 12000,
      quantity: "2",
      unit_price: "60",
      quote: {
        symbol: "ABC",
        exchange: "XETRA",
        mic_code: null,
        name: "ABC",
        fetched_at: "2026-08-11T12:00:00Z",
      },
      fx: { source: "IDENTITY", rate_to_eur: "1", rate_date: "2026-08-11" },
      preview_token: "a".repeat(64),
    };
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        void init;
        return new Response(
          JSON.stringify(
            String(input).includes("quote-preview")
              ? { items: [preview] }
              : { items: [] },
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient();
    const ready = await client.portfolio.previewQuotes(["asset-1", "asset-2"]);
    await client.portfolio.saveQuoteSnapshots(
      ready.filter((item) => item.status === "ready"),
    );
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/portfolio/quote-preview?asset_id=asset-1&asset_id=asset-2",
    );
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      items: [preview],
    });
  });

  it("requests signed monthly history for one asset", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      void input;
      return new Response(
        JSON.stringify({
          asset_id: "asset-1",
          asset_revision: 2,
          source: "YAHOO_FINANCE",
          available_months: 0,
          existing_months: 0,
          first_date: null,
          last_date: null,
          items: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      new ApiClient().portfolio.previewQuoteHistory("asset-1"),
    ).resolves.toMatchObject({
      assetId: "asset-1",
      availableMonths: 0,
      items: [],
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/portfolio/history-preview?asset_id=asset-1",
    );
  });

  it("maps ECB FX preview query parameters", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      void input;
      return new Response(
        JSON.stringify({
          currency: "USD",
          valued_at: "2026-08-11",
          source: "ECB",
          rate_to_eur: "0.91",
          rate_date: "2026-08-10",
          preview_token: "f".repeat(64),
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      new ApiClient().portfolio.previewFx("USD", "2026-08-11"),
    ).resolves.toEqual({
      currency: "USD",
      valuedAt: "2026-08-11",
      source: "ECB",
      rateToEur: "0.91",
      rateDate: "2026-08-10",
      previewToken: "f".repeat(64),
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/portfolio/fx-preview?currency=USD&valued_at=2026-08-11",
    );
  });
});
