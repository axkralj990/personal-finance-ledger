import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import App from "../App";

const valuation = { id: "valuation-1", asset_id: "asset-1", valued_at: "2026-08-07", native_value_minor: 12000, eur_value_minor: 12000, quantity: "2", unit_price: "60", cost_basis_native_minor: 10000, cost_basis_eur_minor: 10000, cost_basis_fx_source: "IDENTITY", cost_basis_fx_rate_to_eur: "1", cost_basis_fx_rate_date: "2026-01-01", source: "TWELVE_DATA", quote_symbol: "ABC", quote_exchange: "XETRA", quote_mic_code: "XETR", quote_name: "ABC Fund", quote_fetched_at: "2026-08-07T12:00:00Z", fx_source: "IDENTITY", fx_rate_to_eur: "1", fx_rate_date: "2026-08-07", created_at: "2026-08-07T12:00:00Z" };
const assets = [
  { id: "asset-1", name: "World ETF", asset_type: "ETF", currency: "EUR", acquisition_date: "2026-01-01", quantity: "2", cost_basis_native_minor: 10000, cost_basis_eur_minor: 10000, cost_basis_fx_source: "IDENTITY", cost_basis_fx_rate_to_eur: "1", cost_basis_fx_rate_date: "2026-01-01", quote: { symbol: "ABC", exchange: "XETRA", mic_code: "XETR" }, is_active: true, revision: 2, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-08-07T12:00:00Z", archived_at: null, latest_valuation: valuation },
  { id: "asset-2", name: "Small Cap ETF", asset_type: "ETF", currency: "EUR", acquisition_date: "2026-02-01", quantity: "1", cost_basis_native_minor: 5000, cost_basis_eur_minor: 5000, cost_basis_fx_source: "IDENTITY", cost_basis_fx_rate_to_eur: "1", cost_basis_fx_rate_date: "2026-02-01", quote: { symbol: "SMALL", exchange: "XETRA", mic_code: null }, is_active: true, revision: 1, created_at: "2026-02-01T00:00:00Z", updated_at: "2026-02-01T00:00:00Z", archived_at: null, latest_valuation: null },
];
const portfolio = {
  as_of: "2026-08-11", generated_at: "2026-08-11T12:00:00Z", currency: "EUR", complete: false,
  missing_asset_ids: ["asset-2"], asset_count: 2, valued_asset_count: 1, known_value_minor: 12000, total_value_minor: null,
  tracked_cost_basis_minor: 10000, unrealized_pnl_minor: 2000, return_percent: "20", pnl_eligible_assets: 2, pnl_covered_assets: 1,
  allocation_by_type: [{ key: "ETF", name: "ETF", value_minor: 12000, percentage: "100" }],
  allocation_by_asset: [{ key: "asset-1", name: "World ETF", value_minor: 12000, percentage: "100" }],
  pnl_by_asset: [
    { asset_id: "asset-1", name: "World ETF", cost_basis_eur_minor: 10000, current_value_eur_minor: 12000, unrealized_pnl_minor: 2000, return_percent: "20" },
    { asset_id: "asset-2", name: "Small Cap ETF", cost_basis_eur_minor: null, current_value_eur_minor: null, unrealized_pnl_minor: null, return_percent: null },
  ],
  holdings: [
    { asset_id: "asset-1", name: "World ETF", asset_type: "ETF", currency: "EUR", revision: 2, quantity: "2", valuation_id: "valuation-1", valued_at: "2026-08-07", source: "TWELVE_DATA", native_value_minor: 12000, eur_value_minor: 12000, cost_basis_eur_minor: 10000, unrealized_pnl_minor: 2000, return_percent: "20", missing_valuation: false },
    { asset_id: "asset-2", name: "Small Cap ETF", asset_type: "ETF", currency: "EUR", revision: 1, quantity: "1", valuation_id: null, valued_at: null, source: null, native_value_minor: null, eur_value_minor: null, cost_basis_eur_minor: null, unrealized_pnl_minor: null, return_percent: null, missing_valuation: true },
  ],
  history: [{ date: "2026-08-11", complete: false, known_value_minor: 12000, total_value_minor: null, tracked_cost_basis_minor: 10000, unrealized_pnl_minor: 2000, pnl_eligible_assets: 2, pnl_covered_assets: 1 }],
};
const readyPreview = { status: "ready", asset_id: "asset-1", asset_revision: 2, source: "YAHOO_FINANCE", quote_interval: "LIVE", valued_at: "2026-08-11", native_currency: "EUR", native_value_minor: 12200, eur_value_minor: 12200, quantity: "2", unit_price: "61", quote: { symbol: "ABC", exchange: "XETRA", mic_code: "XETR", name: "ABC Fund", fetched_at: "2026-08-11T12:00:00Z" }, fx: { source: "IDENTITY", rate_to_eur: "1", rate_date: "2026-08-11" }, preview_token: "c".repeat(64) };

function duplicateTickerFixture() {
  const secondValuation = { ...valuation, id: "valuation-3", asset_id: "asset-3", native_value_minor: 9000, eur_value_minor: 9000, quantity: "1.5", unit_price: "60", cost_basis_native_minor: 7000, cost_basis_eur_minor: 7000 };
  const secondAsset = { ...assets[0], id: "asset-3", acquisition_date: "2026-03-01", quantity: "1.5", cost_basis_native_minor: 7000, cost_basis_eur_minor: 7000, latest_valuation: secondValuation };
  const firstHolding = portfolio.holdings[0]!;
  const secondHolding = { ...firstHolding, asset_id: "asset-3", valuation_id: "valuation-3", quantity: "1.5", native_value_minor: 9000, eur_value_minor: 9000, cost_basis_eur_minor: 7000, unrealized_pnl_minor: 2000, return_percent: "28.571429" };
  return {
    assetItems: [assets[0]!, secondAsset],
    report: {
      ...portfolio,
      complete: true,
      missing_asset_ids: [],
      asset_count: 2,
      valued_asset_count: 2,
      known_value_minor: 21000,
      total_value_minor: 21000,
      tracked_cost_basis_minor: 17000,
      unrealized_pnl_minor: 4000,
      return_percent: "23.529412",
      pnl_eligible_assets: 2,
      pnl_covered_assets: 2,
      allocation_by_asset: [
        { key: "asset-1", name: "World ETF", value_minor: 12000, percentage: "57.142857" },
        { key: "asset-3", name: "World ETF", value_minor: 9000, percentage: "42.857143" },
      ],
      pnl_by_asset: [
        portfolio.pnl_by_asset[0],
        { asset_id: "asset-3", name: "World ETF", cost_basis_eur_minor: 7000, current_value_eur_minor: 9000, unrealized_pnl_minor: 2000, return_percent: "28.571429" },
      ],
      holdings: [firstHolding, secondHolding],
    },
  };
}

function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }); }

function mockPortfolioApi(options: { assetsFail?: boolean; quoteSaveFail?: boolean; report?: Record<string, unknown>; fxDateMismatch?: boolean; assetItems?: Record<string, unknown>[]; historyItems?: Record<string, unknown>[]; createdAsset?: Record<string, unknown>; quoteItems?: Record<string, unknown>[] } = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/health") return json({ status: "ok" });
    if (url === "/api/v1/assets" && init?.method === "POST") return json(options.createdAsset ?? assets[0], 201);
    if (url === "/api/v1/assets") return options.assetsFail ? json({ code: "assets_unavailable", message: "Asset service unavailable" }, 503) : json(options.assetItems ?? assets);
    if (url === "/api/v1/portfolio") return json(options.report ?? portfolio);
    if (url.includes("history-preview")) { const assetId = new URL(url, "http://localhost").searchParams.get("asset_id"); const items = assetId === "asset-1" ? options.historyItems ?? [] : []; return json({ asset_id: assetId, asset_revision: 2, source: "YAHOO_FINANCE", available_months: items.length, existing_months: 0, first_date: items[0] ? "2026-06-30" : null, last_date: items.length ? "2026-07-31" : null, items }); }
    if (url.includes("quote-preview")) return json({ items: options.quoteItems ?? [readyPreview, { status: "error", asset_id: "asset-2", asset_revision: 1, error: { code: "market_data_error", message: "Symbol was not found", recoverable: true } }] });
    if (url.includes("fx-preview")) { const params = new URL(url, "http://localhost").searchParams; const requested = params.get("valued_at"); return json({ currency: params.get("currency"), valued_at: options.fxDateMismatch ? "2026-01-01" : requested, source: "ECB", rate_to_eur: "0.92", rate_date: requested === "2026-08-11" ? "2026-08-10" : requested, preview_token: "e".repeat(64) }); }
    if (url.endsWith("quote-snapshots")) return options.quoteSaveFail ? json({ code: "save_failed", message: "Snapshot write failed" }, 500) : json({ items: [valuation] }, 201);
    if (url.endsWith("/valuations") && !init?.method) return json([valuation]);
    if (url.endsWith("/valuations") && init?.method === "POST") return json(valuation, 201);
    if (url.startsWith("/api/v1/assets/") && init?.method === "PATCH") return json({ ...assets[0], is_active: false, revision: 3 });
    return json({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("PortfolioPage", () => {
  it("renders coverage and stale warnings, then requires review before saving partial quotes", async () => {
    const fetchMock = mockPortfolioApi();
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Capital, with provenance" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Portfolio" })).toHaveLength(2);
    expect(await screen.findByText("Portfolio value is incomplete.")).toBeInTheDocument();
    expect(screen.getAllByText("Missing valuation").length).toBeGreaterThan(0);
    expect(screen.queryByRole("heading", { name: "Portfolio value over time" })).not.toBeInTheDocument();
    expect(screen.getByText("Exact allocation data")).toBeInTheDocument();
    expect(screen.getByText("Exact unrealized P&L data")).toBeInTheDocument();
    expect(screen.getAllByText("Stale quote").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Refresh quotes" }));
    expect(await screen.findByText("Symbol was not found")).toBeInTheDocument();
    expect(screen.getByText("ABC Fund")).toBeInTheDocument();
    expect(screen.getByText("Yahoo Finance")).toBeInTheDocument();
    expect(screen.getByText(/Nothing below changes the portfolio until saved/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("quote-snapshots"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Save reviewed purchases (1)" }));
    expect(await screen.findByText(/1 reviewed quote saved; 1 preview failure/)).toBeInTheDocument();
    const snapshotCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("quote-snapshots"));
    expect(JSON.parse(String(snapshotCall?.[1]?.body)).items).toHaveLength(1);
    expect(JSON.parse(String(snapshotCall?.[1]?.body)).items[0].asset_id).toBe("asset-1");
    expect(JSON.parse(String(snapshotCall?.[1]?.body)).items[0].preview_token).toBe("c".repeat(64));
  });

  it("flags mixed market sources inside one grouped quote review", async () => {
    const fixture = duplicateTickerFixture();
    const secondPreview = {
      ...readyPreview,
      asset_id: "asset-3",
      asset_revision: 1,
      quantity: "1.5",
      native_value_minor: 9150,
      eur_value_minor: 9150,
      quote: { ...readyPreview.quote, symbol: "DIFFERENT" },
    };
    mockPortfolioApi({ ...fixture, quoteItems: [readyPreview, secondPreview] });
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });

    await user.click(screen.getByRole("button", { name: "Refresh quotes" }));
    expect(await screen.findByText("Mixed instruments")).toBeInTheDocument();
    expect(screen.getByText("1 ready / 0 partial / 0 failed")).toBeInTheDocument();
  });

  it("backfills missing monthly history in one signed batch", async () => {
    const historyItems = [
      { ...readyPreview, quote_interval: "MONTHLY", valued_at: "2026-06-30", preview_token: "d".repeat(64) },
      { ...readyPreview, quote_interval: "MONTHLY", valued_at: "2026-07-31", preview_token: "e".repeat(64) },
    ];
    const lseAsset = { ...assets[0], quote: { symbol: "ABC", exchange: "LSEETF", mic_code: "XLON" } };
    const fetchMock = mockPortfolioApi({ historyItems, assetItems: [lseAsset, assets[1]!] });
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });

    await user.click(screen.getByRole("button", { name: "Update history" }));
    expect(await screen.findByText("2 monthly snapshots saved.")).toBeInTheDocument();
    const snapshotCall = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith("quote-snapshots") && init?.method === "POST");
    expect(JSON.parse(String(snapshotCall?.[1]?.body)).items).toHaveLength(2);
  });

  it("adds a backdated manual valuation and archives with revision protection", async () => {
    const fetchMock = mockPortfolioApi();
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });

    await user.click(screen.getAllByRole("button", { name: "Add valuation" })[0]!);
    const valueDialog = screen.getByRole("dialog", { name: "Value World ETF" });
    expect(within(valueDialog).getByLabelText("Price per share (EUR)")).toHaveValue("");
    expect(within(valueDialog).queryByLabelText("Current value (EUR)")).not.toBeInTheDocument();
    await user.type(within(valueDialog).getByLabelText("Price per share (EUR)"), "65");
    expect(within(valueDialog).getByText("€130.00")).toBeInTheDocument();
    await user.click(within(valueDialog).getByRole("button", { name: "Add valuation" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/valuations") && init?.method === "POST")).toBe(true));
    const valuationCall = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith("/valuations") && init?.method === "POST");
    expect(JSON.parse(String(valuationCall?.[1]?.body))).toMatchObject({ expected_revision: 2, native_value_minor: 13000, unit_price: "65" });

    await user.click(screen.getAllByRole("button", { name: "Edit World ETF" })[0]!);
    const editDialog = screen.getByRole("dialog", { name: "Edit World ETF" });
    expect(within(editDialog).getByLabelText("Date bought")).toBeDisabled();
    expect(within(editDialog).getByLabelText("MIC code")).toHaveValue("XETR");
    await user.click(within(editDialog).getByRole("button", { name: "Archive asset" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === "/api/v1/assets/asset-1" && init?.method === "PATCH")).toBe(true));
    const archiveCall = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/v1/assets/asset-1" && init?.method === "PATCH");
    expect(JSON.parse(String(archiveCall?.[1]?.body))).toEqual({ expected_revision: 2, is_active: false });
  });

  it("groups matching ticker lots and expands their purchase details", async () => {
    const fixture = duplicateTickerFixture();
    mockPortfolioApi(fixture);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });

    const holdings = screen.getByRole("table", { name: "Active portfolio positions with expandable purchase lots" });
    const disclosure = within(holdings).getByRole("button", { name: /World ETF.*2 purchases/ });
    const groupRow = disclosure.closest("tr")!;
    expect(within(groupRow).getByText("3.5")).toBeInTheDocument();
    expect(within(groupRow).getByText("€210.00")).toBeInTheDocument();
    expect(within(groupRow).getByText("€170.00")).toBeInTheDocument();
    expect(within(groupRow).getByText("€40.00")).toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "Ranked allocation by asset" })).getAllByText("World ETF")).toHaveLength(1);
    expect(within(screen.getByRole("table", { name: "Exact unrealized profit and loss by asset" })).getAllByText("World ETF")).toHaveLength(1);

    await user.click(disclosure);
    expect(within(holdings).getByText("Purchased 01 Jan 2026")).toBeInTheDocument();
    expect(within(holdings).getByText("Purchased 01 Mar 2026")).toBeInTheDocument();
    expect(within(holdings).getAllByRole("button", { name: "Edit World ETF" })).toHaveLength(2);
  });

  it("shows partial grouped valuation and P&L coverage on desktop and mobile", async () => {
    const fixture = duplicateTickerFixture();
    const missingHolding = {
      ...fixture.report.holdings[1],
      valuation_id: null,
      valued_at: null,
      source: null,
      native_value_minor: null,
      eur_value_minor: null,
      cost_basis_eur_minor: null,
      unrealized_pnl_minor: null,
      return_percent: null,
      missing_valuation: true,
    };
    mockPortfolioApi({
      ...fixture,
      report: {
        ...fixture.report,
        complete: false,
        missing_asset_ids: ["asset-3"],
        valued_asset_count: 1,
        known_value_minor: 12000,
        total_value_minor: null,
        holdings: [fixture.report.holdings[0], missingHolding],
      },
    });
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });

    expect(screen.getAllByText("1 of 2 purchases valued")).toHaveLength(2);
    expect(screen.getAllByText("1 of 2 purchases covered")).toHaveLength(2);
  });

  it("adds a purchase with its ticker group identity locked", async () => {
    const fixture = duplicateTickerFixture();
    const createdAsset = { ...assets[0], id: "asset-4" };
    const fetchMock = mockPortfolioApi({ ...fixture, createdAsset });
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });

    const holdings = screen.getByRole("table", { name: "Active portfolio positions with expandable purchase lots" });
    await user.click(within(holdings).getByRole("button", { name: "Add ABC on XETRA purchase" }));
    const dialog = screen.getByRole("dialog", { name: "Add ABC purchase" });
    expect(within(dialog).getByLabelText("Ticker")).toBeDisabled();
    expect(within(dialog).getByLabelText("Ticker")).toHaveValue("ABC");
    expect(within(dialog).getByLabelText("Asset type")).toBeDisabled();
    expect(within(dialog).getByLabelText("Currency")).toBeDisabled();
    expect(within(dialog).getByLabelText("Exchange")).toBeDisabled();
    expect(within(dialog).getByLabelText("Exchange")).toHaveValue("XETRA");
    await user.type(within(dialog).getByLabelText("Number of shares"), "1.25");
    await user.type(within(dialog).getByLabelText("Purchase price per share (EUR)"), "50");
    await user.click(within(dialog).getByRole("button", { name: "Add purchase" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === "/api/v1/assets" && init?.method === "POST")).toBe(true));
    const createCall = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/v1/assets" && init?.method === "POST");
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({
      name: "ABC",
      asset_type: "ETF",
      currency: "EUR",
      quantity: "1.25",
      cost_basis_native_minor: 6250,
      quote: { symbol: "ABC", exchange: "XETRA", mic_code: "XETR" },
    });
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-preview?asset_id=asset-4&asset_id=asset-1&asset_id=asset-3"))).toBe(true));
    const groupQuoteCall = fetchMock.mock.calls.find(([url]) => String(url).includes("quote-preview?asset_id=asset-4&asset_id=asset-1&asset_id=asset-3"));
    expect(groupQuoteCall).toBeDefined();
  });

  it("adds a purchase to a MIC-only ticker group", async () => {
    const micAsset = { ...assets[0], quote: { symbol: "ABC", exchange: null, mic_code: "XLON" } };
    const report = {
      ...portfolio,
      complete: true,
      missing_asset_ids: [],
      asset_count: 1,
      valued_asset_count: 1,
      pnl_eligible_assets: 1,
      pnl_covered_assets: 1,
      holdings: [portfolio.holdings[0]],
      pnl_by_asset: [portfolio.pnl_by_asset[0]],
    };
    const fetchMock = mockPortfolioApi({ assetItems: [micAsset], report });
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });

    const holdings = screen.getByRole("table", { name: "Active portfolio positions with expandable purchase lots" });
    await user.click(within(holdings).getByRole("button", { name: "Add ABC on XLON purchase" }));
    const dialog = screen.getByRole("dialog", { name: "Add ABC purchase" });
    expect(within(dialog).getByLabelText("Exchange")).toBeDisabled();
    expect(within(dialog).getByLabelText("Exchange")).toHaveValue("");
    expect(within(dialog).getByLabelText("MIC code")).toBeDisabled();
    expect(within(dialog).getByLabelText("MIC code")).toHaveValue("XLON");
    await user.type(within(dialog).getByLabelText("Number of shares"), "1");
    await user.type(within(dialog).getByLabelText("Purchase price per share (EUR)"), "50");
    await user.click(within(dialog).getByRole("button", { name: "Add purchase" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === "/api/v1/assets" && init?.method === "POST")).toBe(true));
    const createCall = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/v1/assets" && init?.method === "POST");
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({
      quote: { symbol: "ABC", exchange: null, mic_code: "XLON" },
    });
  });

  it("keeps a ticker entered before selecting a security type", async () => {
    const fetchMock = mockPortfolioApi();
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });
    await user.click(screen.getByRole("button", { name: "Add asset" }));
    const dialog = screen.getByRole("dialog", { name: "Add asset" });
    await user.type(within(dialog).getByLabelText("Asset name"), "CSPX");
    await user.selectOptions(within(dialog).getByLabelText("Asset type"), "ETF");
    expect(within(dialog).getByLabelText("Ticker")).toHaveValue("CSPX");
    await user.type(within(dialog).getByLabelText("Number of shares"), "1");
    await user.type(within(dialog).getByLabelText("Purchase price per share (EUR)"), "50");
    await user.type(within(dialog).getByLabelText("Exchange"), "LSEETF");
    await user.click(within(dialog).getByRole("button", { name: "Add investment" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === "/api/v1/assets" && init?.method === "POST")).toBe(true));
    const createCall = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/v1/assets" && init?.method === "POST");
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({
      name: "CSPX",
      quote: { symbol: "CSPX", exchange: "LSEETF" },
    });
  });

  it("creates a security from purchase facts and automatically saves its current quote", async () => {
    const fetchMock = mockPortfolioApi();
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });
    await user.click(screen.getByRole("button", { name: "Add asset" }));
    const dialog = screen.getByRole("dialog", { name: "Add asset" });
    expect(within(dialog).queryByLabelText("Quantity")).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("Current balance (EUR)")).toBeInTheDocument();
    await user.selectOptions(within(dialog).getByLabelText("Asset type"), "FIXED_ASSET");
    expect(within(dialog).getByLabelText("Estimated value (EUR)")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Quantity")).not.toBeInTheDocument();
    await user.selectOptions(within(dialog).getByLabelText("Asset type"), "ETF");
    expect(within(dialog).getByLabelText("Number of shares")).toBeInTheDocument();
    expect(within(dialog).getByText("Latest market price")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Current value (EUR)")).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Track profit and loss")).not.toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Ticker"), "CSPX");
    await user.type(within(dialog).getByLabelText("Number of shares"), "2");
    await user.type(within(dialog).getByLabelText("Purchase price per share (EUR)"), "65");
    await user.type(within(dialog).getByLabelText("Exchange"), "LSEETF");
    expect(within(dialog).getByText("€130.00")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Add investment" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === "/api/v1/assets" && init?.method === "POST")).toBe(true));
    const createCall = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/v1/assets" && init?.method === "POST");
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({ name: "CSPX", quantity: "2", cost_basis_native_minor: 13000, cost_basis_eur_minor: 13000, quote: { symbol: "CSPX", exchange: "LSEETF" }, initial_valuation: { native_value_minor: 13000, unit_price: "65" } });
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-preview?asset_id=asset-1"))).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("quote-snapshots"))).toBe(true);
  });

  it("keeps a created purchase when the automatic current quote cannot be saved", async () => {
    const fetchMock = mockPortfolioApi({ quoteSaveFail: true });
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });
    await user.click(screen.getByRole("button", { name: "Add asset" }));
    const dialog = screen.getByRole("dialog", { name: "Add asset" });
    await user.selectOptions(within(dialog).getByLabelText("Asset type"), "ETF");
    await user.type(within(dialog).getByLabelText("Ticker"), "CSPX");
    await user.type(within(dialog).getByLabelText("Number of shares"), "2");
    await user.type(within(dialog).getByLabelText("Purchase price per share (EUR)"), "65");
    await user.type(within(dialog).getByLabelText("Exchange"), "LSEETF");
    await user.click(within(dialog).getByRole("button", { name: "Add investment" }));

    expect(await screen.findByText(/Snapshot write failed/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url) === "/api/v1/assets" && init?.method === "POST")).toHaveLength(1);
    expect(screen.queryByRole("dialog", { name: "Add asset" })).not.toBeInTheDocument();
  });

  it("keeps purchase facts immutable and refreshes the real quote without a synthetic value", async () => {
    const assetWithoutUnitPrice = { ...assets[0], latest_valuation: { ...valuation, unit_price: null } };
    const fetchMock = mockPortfolioApi({ assetItems: [assetWithoutUnitPrice, assets[1]!] });
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });

    await user.click(screen.getAllByRole("button", { name: "Edit World ETF" })[0]!);
    const dialog = screen.getByRole("dialog", { name: "Edit World ETF" });
    expect(within(dialog).queryByText("Value after this change")).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("Purchase price per share (EUR)")).toHaveValue("50");
    expect(within(dialog).getByLabelText("Purchase price per share (EUR)")).toBeDisabled();
    expect(within(dialog).getByLabelText("Number of shares")).toBeDisabled();
    expect(within(dialog).getByLabelText("Asset type")).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("quote-snapshots"))).toBe(true));
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === "/api/v1/assets/asset-1" && init?.method === "PATCH")).toBe(false);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("quote-snapshots"))).toBe(true);
  });

  it("automatically uses the date-bought ECB rate for a non-EUR purchase", async () => {
    const fetchMock = mockPortfolioApi();
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });
    await user.click(screen.getByRole("button", { name: "Add asset" }));
    const dialog = screen.getByRole("dialog", { name: "Add asset" });
    await user.selectOptions(within(dialog).getByLabelText("Asset type"), "ETF");
    await user.type(within(dialog).getByLabelText("Ticker"), "CSPX");
    await user.selectOptions(within(dialog).getByLabelText("Currency"), "USD");
    await user.clear(within(dialog).getByLabelText("Date bought"));
    await user.type(within(dialog).getByLabelText("Date bought"), "2022-10-02");
    await user.type(within(dialog).getByLabelText("Number of shares"), "2");
    await user.type(within(dialog).getByLabelText("Purchase price per share (USD)"), "465.06");
    await user.type(within(dialog).getByLabelText("Exchange"), "LSEETF");
    await user.click(within(dialog).getByRole("button", { name: "Add investment" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("fx-preview?currency=USD&valued_at=2022-10-02"))).toBe(true));
    const createCall = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/v1/assets" && init?.method === "POST");
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({ acquisition_date: "2022-10-02", quantity: "2", cost_basis_native_minor: 93012, cost_basis_fx_source: "ECB", cost_basis_fx_preview_token: "e".repeat(64), initial_valuation: { valued_at: "2022-10-02", native_value_minor: 93012, unit_price: "465.06", fx_source: "ECB", fx_preview_token: "e".repeat(64) } });
  });

  it("loads cash ECB rates and resets drawers", async () => {
    const fetchMock = mockPortfolioApi();
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });
    await user.click(screen.getByRole("button", { name: "Add asset" }));
    let dialog = screen.getByRole("dialog", { name: "Add asset" });
    await user.type(within(dialog).getByLabelText("Asset name"), "Temporary");
    await user.selectOptions(within(dialog).getByLabelText("Currency"), "USD");
    await user.click(within(dialog).getByRole("button", { name: "Use ECB rate" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/fx-preview?currency=USD"))).toBe(true));
    expect(within(dialog).getByText(/ECB rate 0.92 from 2026-08-\d{2}/)).toBeInTheDocument();
    await user.click(within(dialog).getAllByRole("button", { name: "Close details" }).at(-1)!);
    await user.click(screen.getByRole("button", { name: "Add asset" }));
    dialog = screen.getByRole("dialog", { name: "Add asset" });
    expect(within(dialog).getByLabelText("Asset name")).toHaveValue("");
    await user.click(within(dialog).getAllByRole("button", { name: "Close details" }).at(-1)!);

  });

  it("preserves quote review and previous values when snapshot save fails", async () => {
    mockPortfolioApi({ quoteSaveFail: true });
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });
    await user.click(screen.getByRole("button", { name: "Refresh quotes" }));
    await user.click(await screen.findByRole("button", { name: "Save reviewed purchases (1)" }));
    expect(await screen.findByText(/No quote values were changed. Snapshot write failed/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Review quotes before saving" })).toBeInTheDocument();
    expect(screen.getAllByText("€120.00").length).toBeGreaterThan(0);
  });

  it("keeps the report visible and disables management when assets fail", async () => {
    mockPortfolioApi({ assetsFail: true });
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    expect(await screen.findByText(/portfolio report remains available in read-only mode/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Where value is held" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add asset" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Refresh quotes" })).toBeDisabled();
  });

  it("renders archived portfolio history when there are no active assets", async () => {
    mockPortfolioApi({ report: { ...portfolio, asset_count: 0, valued_asset_count: 0, known_value_minor: 0, total_value_minor: 0, tracked_cost_basis_minor: null, unrealized_pnl_minor: null, return_percent: null, pnl_eligible_assets: 0, pnl_covered_assets: 0, allocation_by_type: [], allocation_by_asset: [], pnl_by_asset: [], holdings: [] } });
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    expect(await screen.findByText("No active assets")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Portfolio value over time" })).not.toBeInTheDocument();
    expect(screen.getByText("No known allocation")).toBeInTheDocument();
  });

  it("discards an FX preview whose echoed date does not match the request", async () => {
    mockPortfolioApi({ fxDateMismatch: true });
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/portfolio"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Capital, with provenance" });
    await user.click(screen.getByRole("button", { name: "Add asset" }));
    const dialog = screen.getByRole("dialog", { name: "Add asset" });
    await user.selectOptions(within(dialog).getByLabelText("Currency"), "USD");
    await user.click(within(dialog).getByRole("button", { name: "Use ECB rate" }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Use ECB rate" })).toBeEnabled());
    expect(within(dialog).getByLabelText("Manual FX rate to EUR")).toHaveValue("");
    expect(within(dialog).getByText("No conversion rate selected")).toBeInTheDocument();
  });
});
