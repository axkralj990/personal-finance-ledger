import {
  mapCategory,
  mapImportBatch,
  mapAsset,
  mapPortfolio,
  mapQuoteHistoryPreview,
  mapQuotePreview,
  mapReportSummary,
  mapSourceAccount,
  mapStagedTransaction,
  mapTagRule,
  mapTransaction,
} from "./mappers";

describe("backend contract mappers", () => {
  it("maps realistic snake_case API responses", () => {
    expect(mapSourceAccount({
      id: "account-1",
      provider: "MANUAL",
      display_name: "Manual",
      default_currency: "EUR",
      is_active: false,
    }).active).toBe(false);

    expect(mapCategory({
      id: "category-1",
      display_name: "Food",
      sort_order: 2,
      is_active: true,
      subcategories: [{
        id: "subcategory-1",
        category_id: "category-1",
        display_name: "Cafes",
        sort_order: 1,
        is_active: false,
      }],
    })).toMatchObject({
      name: "Food",
      active: true,
      subcategories: [{ name: "Cafes", active: false }],
    });

    expect(mapImportBatch({
      id: "batch-1",
      source_account_id: "account-1",
      original_filename: "manual-entry",
      status: "NEEDS_REVIEW",
      total_rows: 1,
      valid_rows: 0,
      needs_review_rows: 1,
      duplicate_rows: 1,
      ignored_rows: 0,
      errors: ["Review required"],
      created_at: "2026-08-09T10:00:00Z",
      updated_at: "2026-08-09T10:00:00Z",
    })).toMatchObject({
      validRows: 0,
      needsReviewRows: 1,
      duplicateRows: 1,
      errors: ["Review required"],
    });

    expect(mapStagedTransaction({
      id: "row-1",
      row_number: 1,
      revision: 1,
      transaction_date: "2026-08-09",
      description: "Cafe",
      amount_minor: -450,
      currency: "EUR",
      kind: "EXPENSE",
      category_id: null,
      subcategory_id: null,
      predicted_category_id: "food",
      predicted_subcategory_id: "cafes",
      prediction_confidence: 0.74,
      validation_issues: [],
      duplicate_status: "LIKELY",
      duplicate_candidate_id: "transaction-1",
      duplicate_candidate: {
        id: "transaction-1",
        transaction_date: "2026-08-08",
        description: "Cafe",
        amount_minor: -450,
        currency: "EUR",
        source_account_name: "Manual",
      },
      duplicate_explanation: "same amount",
      disposition: "PENDING",
      ignore_reason: null,
      remember_correction: false,
      raw_json: { Description: "Cafe" },
    })).toMatchObject({
      confidence: 0.74,
      duplicateState: "LIKELY",
      duplicateCandidate: { id: "transaction-1" },
      disposition: "PENDING",
      needsReview: true,
      raw: { Description: "Cafe" },
    });

    expect(mapTransaction({
      id: "transaction-1",
      revision: 2,
      transaction_date: "2026-08-09",
      description: "Cafe",
      amount_minor: -450,
      currency: "EUR",
      kind: "EXPENSE",
      source_account_id: "account-1",
      source_account_name: "Manual",
      category_id: "food",
      category_name: "Food",
      subcategory_id: "cafes",
      subcategory_name: "Cafes",
      is_excluded: true,
      import_batch_id: "batch-1",
    })).toMatchObject({
      sourceAccountName: "Manual",
      categoryName: "Food",
      subcategoryName: "Cafes",
      excluded: true,
    });

    expect(mapReportSummary({
      currency: "EUR",
      income_minor: 1000,
      spending_minor: 450,
      net_flow_minor: 550,
    }).netMinor).toBe(550);
  });

  it("preserves nullable staged repair fields instead of fabricating values", () => {
    expect(mapStagedTransaction({
      id: "invalid-row",
      row_number: 9,
      revision: 1,
      transaction_date: null,
      description: null,
      amount_minor: null,
      currency: null,
      kind: null,
      validation_issues: [{ message: "Could not parse amount" }],
      disposition: "PENDING",
    })).toMatchObject({
      date: null,
      description: null,
      amountMinor: null,
      currency: null,
      kind: null,
      errors: ["Could not parse amount"],
    });
  });

  it("maps provider-scoped tag rules", () => {
    expect(mapTagRule({
      id: "rule-1",
      description: "COFFEE",
      scope: "PROVIDER",
      provider: "REVOLUT",
      category_id: "food",
      is_enabled: true,
    })).toMatchObject({ provider: "REVOLUT", scope: "PROVIDER", active: true });
  });

  it("maps portfolio contracts defensively from snake_case", () => {
    expect(mapAsset({
      id: "asset-1", name: "World ETF", asset_type: "ETF", currency: "EUR", acquisition_date: "2025-01-01",
      quantity: "2.5", cost_basis_native_minor: 10000, cost_basis_eur_minor: 10000, cost_basis_fx_source: "IDENTITY", cost_basis_fx_rate_to_eur: "1", cost_basis_fx_rate_date: "2025-01-01",
      quote: { symbol: "VWCE", exchange: "XETRA", mic_code: "XETR" }, is_active: false, revision: 3, archived_on: "2026-08-11",
      latest_valuation: { id: "v-1", asset_id: "asset-1", valued_at: "2026-08-11", native_value_minor: 12500, eur_value_minor: 12500, source: "TWELVE_DATA", fx_source: "IDENTITY", fx_rate_to_eur: "1", fx_rate_date: "2026-08-11" },
    })).toMatchObject({ assetType: "ETF", costBasisEurMinor: 10000, costBasisFxSource: "IDENTITY", archivedOn: "2026-08-11", quote: { micCode: "XETR" }, latestValuation: { eurValueMinor: 12500 } });

    expect(mapPortfolio({
      as_of: "2026-08-11", generated_at: "2026-08-11T12:00:00Z", currency: "EUR", complete: false,
      missing_asset_ids: ["asset-2"], asset_count: 2, valued_asset_count: 1, known_value_minor: 12500,
      total_value_minor: null, tracked_cost_basis_minor: 10000, unrealized_pnl_minor: 2500, return_percent: "25",
      pnl_eligible_assets: 2, pnl_covered_assets: 1,
      allocation_by_type: [{ key: "ETF", name: "ETF", value_minor: 12500, percentage: "100" }],
      allocation_by_asset: [], pnl_by_asset: [],
      holdings: [{ asset_id: "asset-2", name: "Home", asset_type: "FIXED_ASSET", currency: "EUR", revision: 1, missing_valuation: true }],
      history: [{ date: "2026-08-11", complete: false, known_value_minor: 12500, total_value_minor: null, pnl_eligible_assets: 2, pnl_covered_assets: 1 }],
    })).toMatchObject({ complete: false, missingAssetIds: ["asset-2"], totalValueMinor: null, holdings: [{ missingValuation: true }], history: [{ knownValueMinor: 12500 }] });
  });

  it("keeps ready and error quote previews discriminated", () => {
    const items = mapQuotePreview({ items: [
      { status: "ready", asset_id: "asset-1", asset_revision: 2, source: "YAHOO_FINANCE", valued_at: "2026-08-11", native_currency: "USD", native_value_minor: 1000, eur_value_minor: 900, quantity: "2", unit_price: "5", quote: { symbol: "ABC", exchange: "NYSE", mic_code: "XNYS", name: "ABC Inc", fetched_at: "2026-08-11T12:00:00Z" }, fx: { source: "ECB", rate_to_eur: "0.9", rate_date: "2026-08-10" }, preview_token: "b".repeat(64) },
      { status: "error", asset_id: "asset-2", asset_revision: 1, error: { code: "quote_failed", message: "Provider unavailable", recoverable: true } },
    ] });
    expect(items[0]).toMatchObject({ status: "ready", source: "YAHOO_FINANCE", assetId: "asset-1", previewToken: "b".repeat(64), quote: { micCode: "XNYS" }, fx: { rateToEur: "0.9" } });
    expect(items[1]).toMatchObject({ status: "error", assetId: "asset-2", error: { message: "Provider unavailable" } });
  });

  it("maps signed monthly history preview metadata", () => {
    const ready = { status: "ready", asset_id: "asset-1", asset_revision: 2, source: "YAHOO_FINANCE", quote_interval: "MONTHLY", valued_at: "2026-07-31", native_currency: "USD", native_value_minor: 1000, eur_value_minor: 900, quantity: "2", unit_price: "5", quote: { symbol: "CSPX", exchange: "LSE", mic_code: null, name: "CSPX", fetched_at: "2026-08-11T12:00:00Z" }, fx: { source: "ECB", rate_to_eur: "0.9", rate_date: "2026-07-31" }, preview_token: "h".repeat(64) };
    expect(mapQuoteHistoryPreview({ asset_id: "asset-1", asset_revision: 2, source: "YAHOO_FINANCE", available_months: 4, existing_months: 3, first_date: "2026-04-30", last_date: "2026-07-31", items: [ready] })).toMatchObject({ assetId: "asset-1", availableMonths: 4, existingMonths: 3, items: [{ source: "YAHOO_FINANCE", valuedAt: "2026-07-31" }] });
  });

  it("fails closed on unknown or unsigned ready quote statuses", () => {
    expect(() => mapQuotePreview({ items: [{ status: "pending" }] })).toThrow(/unknown or missing status/);
    expect(() => mapQuotePreview({ items: [{ status: "ready", native_value_minor: 1, eur_value_minor: 1, preview_token: "short" }] })).toThrow(/malformed/);
  });
});
