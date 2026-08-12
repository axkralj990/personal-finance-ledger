import { ApiClient } from "./client";
import type { ManualTransactionInput } from "./types";

const batchResponse = {
  id: "batch-1",
  source_account_id: "manual-account",
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
  it("sends one top-level account for manual rows", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(JSON.stringify(batchResponse), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const input: ManualTransactionInput = {
      sourceAccountId: "manual-account",
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
      source_account_id: "manual-account",
      rows: [{
        transaction_date: "2026-08-09",
        description: "Cafe",
        amount_minor: -450,
        currency: "EUR",
        category_id: null,
        subcategory_id: null,
      }],
    });
  });

  it("collects every bounded staged-row page", async () => {
    const firstPage = Array.from({ length: 500 }, (_, index) => stagedRow(index + 1));
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
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(JSON.stringify([stagedRow(1)]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await new ApiClient().imports.patchRows("batch-1", [{
      id: "row-1",
      expectedRevision: 2,
      transactionDate: "2026-08-08",
      description: "Repaired",
      amountMinor: null,
      currency: "SGD",
    }]);

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ rows: [{
      id: "row-1",
      expected_revision: 2,
      transaction_date: "2026-08-08",
      description: "Repaired",
      amount_minor: null,
      currency: "SGD",
    }] });
  });

  it("sends include_excluded in transaction queries", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(JSON.stringify({ items: [], page: 1, page_size: 25, total: 0 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await new ApiClient().transactions.list({ includeExcluded: true, search: "Synthetic cafe" });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/transactions?search=Synthetic+cafe&include_excluded=true");
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
      source_account_id: "account-1",
      source_account_name: "Manual EUR",
      category_id: null,
      category_name: null,
      subcategory_id: null,
      subcategory_name: null,
      is_excluded: false,
      import_batch_id: "batch-1",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
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
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(null, { status: 204 });
    });
    vi.stubGlobal("fetch", fetchMock);

    await new ApiClient().transactions.delete("transaction-1", 4);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/transactions/transaction-1");
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("DELETE");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      expected_revision: 4,
      reason: "USER_DELETED",
    });
  });

  it("preserves provider scope when creating and toggling tag rules", async () => {
    const response = {
      id: "rule-1",
      description: "COFFEE",
      scope: "PROVIDER",
      provider: "REVOLUT",
      source_account_id: null,
      category_id: "food",
      subcategory_id: null,
      is_enabled: true,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(JSON.stringify(response), {
      status: 200,
      headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient();

    await client.tagRules.create({
      match: "COFFEE",
      scope: "PROVIDER",
      provider: "REVOLUT",
      sourceAccountId: null,
      categoryId: "food",
      subcategoryId: null,
    });
    await client.tagRules.patch("rule-1", { active: false });

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toMatchObject({ provider: "REVOLUT", scope: "PROVIDER" });
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/tag-rules/rule-1");
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({ is_enabled: false });
  });

  it("serializes asset creation with initial valuation in exact snake_case", async () => {
    const response = { id: "asset-1", name: "World ETF", asset_type: "ETF", currency: "USD", acquisition_date: "2026-01-01", quantity: "2.5", cost_basis_native_minor: 10000, cost_basis_eur_minor: 9200, quote: { symbol: "VWCE", exchange: "XETRA", mic_code: "XETR" }, is_active: true, revision: 1 };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => { void input; void init; return new Response(JSON.stringify(response), { status: 201, headers: { "Content-Type": "application/json" } }); });
    vi.stubGlobal("fetch", fetchMock);
    await new ApiClient().assets.create({ name: "World ETF", assetType: "ETF", currency: "USD", acquisitionDate: "2026-01-01", quantity: "2.5", costBasisNativeMinor: 10000, costBasisEurMinor: 9200, costBasisFxSource: "ECB", costBasisFxRateToEur: "0.92", costBasisFxRateDate: "2025-12-31", costBasisFxPreviewToken: "d".repeat(64), quote: { symbol: "VWCE", exchange: "XETRA", micCode: "XETR" }, initialValuation: { valuedAt: "2026-08-11", nativeValueMinor: 12500, unitPrice: "50", fxSource: "ECB", fxRateToEur: "0.92", fxRateDate: "2026-08-10", fxPreviewToken: "e".repeat(64) } });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/assets");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ name: "World ETF", asset_type: "ETF", currency: "USD", acquisition_date: "2026-01-01", quantity: "2.5", cost_basis_native_minor: 10000, cost_basis_eur_minor: 9200, cost_basis_fx_source: "ECB", cost_basis_fx_rate_to_eur: "0.92", cost_basis_fx_rate_date: "2025-12-31", cost_basis_fx_preview_token: "d".repeat(64), quote: { symbol: "VWCE", exchange: "XETRA", mic_code: "XETR" }, initial_valuation: { valued_at: "2026-08-11", native_value_minor: 12500, unit_price: "50", fx_source: "ECB", fx_rate_to_eur: "0.92", fx_rate_date: "2026-08-10", fx_preview_token: "e".repeat(64) } });
  });

  it("serializes manual valuations and revision-protected archive", async () => {
    const valuation = { id: "v-2", asset_id: "asset-1", valued_at: "2026-07-31", native_value_minor: 11000, eur_value_minor: 10120, source: "MANUAL", fx_source: "MANUAL", fx_rate_to_eur: "0.92", fx_rate_date: "2026-07-31" };
    const asset = { id: "asset-1", name: "World ETF", asset_type: "ETF", currency: "USD", acquisition_date: "2026-01-01", is_active: false, revision: 4 };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => { void init; return new Response(JSON.stringify(String(input).endsWith("valuations") ? valuation : asset), { status: 200, headers: { "Content-Type": "application/json" } }); });
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient();
    await client.assets.addValuation("asset-1", { expectedRevision: 3, valuedAt: "2026-07-31", nativeValueMinor: 11000, fxSource: "MANUAL", fxRateToEur: "0.92", fxRateDate: "2026-07-31", fxPreviewToken: "x".repeat(64) });
    await client.assets.patch("asset-1", { expectedRevision: 3, isActive: false });
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ expected_revision: 3, valued_at: "2026-07-31", native_value_minor: 11000, fx_source: "MANUAL", fx_rate_to_eur: "0.92", fx_rate_date: "2026-07-31" });
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({ expected_revision: 3, is_active: false });
  });

  it("uses repeated preview ids and persists ready previews unchanged", async () => {
    const preview = { status: "ready", asset_id: "asset-1", asset_revision: 2, source: "TWELVE_DATA", quote_interval: "LIVE", valued_at: "2026-08-11", native_currency: "EUR", native_value_minor: 12000, eur_value_minor: 12000, quantity: "2", unit_price: "60", quote: { symbol: "ABC", exchange: "XETRA", mic_code: null, name: "ABC", fetched_at: "2026-08-11T12:00:00Z" }, fx: { source: "IDENTITY", rate_to_eur: "1", rate_date: "2026-08-11" }, preview_token: "a".repeat(64) };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => { void init; return new Response(JSON.stringify(String(input).includes("quote-preview") ? { items: [preview] } : { items: [] }), { status: 200, headers: { "Content-Type": "application/json" } }); });
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient();
    const ready = await client.portfolio.previewQuotes(["asset-1", "asset-2"]);
    await client.portfolio.saveQuoteSnapshots(ready.filter((item) => item.status === "ready"));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/portfolio/quote-preview?asset_id=asset-1&asset_id=asset-2");
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({ items: [preview] });
  });

  it("requests signed monthly history for one asset", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => { void input; return new Response(JSON.stringify({ asset_id: "asset-1", asset_revision: 2, source: "YAHOO_FINANCE", available_months: 0, existing_months: 0, first_date: null, last_date: null, items: [] }), { status: 200, headers: { "Content-Type": "application/json" } }); });
    vi.stubGlobal("fetch", fetchMock);
    await expect(new ApiClient().portfolio.previewQuoteHistory("asset-1")).resolves.toMatchObject({ assetId: "asset-1", availableMonths: 0, items: [] });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/portfolio/history-preview?asset_id=asset-1");
  });

  it("maps ECB FX preview query parameters", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => { void input; return new Response(JSON.stringify({ currency: "USD", valued_at: "2026-08-11", source: "ECB", rate_to_eur: "0.91", rate_date: "2026-08-10", preview_token: "f".repeat(64) }), { status: 200, headers: { "Content-Type": "application/json" } }); });
    vi.stubGlobal("fetch", fetchMock);
    await expect(new ApiClient().portfolio.previewFx("USD", "2026-08-11")).resolves.toEqual({ currency: "USD", valuedAt: "2026-08-11", source: "ECB", rateToEur: "0.91", rateDate: "2026-08-10", previewToken: "f".repeat(64) });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/portfolio/fx-preview?currency=USD&valued_at=2026-08-11");
  });
});
