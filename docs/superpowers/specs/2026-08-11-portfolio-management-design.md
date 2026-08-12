# Portfolio Management Design

## Goal

Add a separate portfolio domain for manually managed assets, dated valuations, optional
market quotes, EUR portfolio totals, allocation, history, and unrealized profit and loss.
The portfolio does not infer balances from ledger transactions.

## Scope

- Asset types: Bank Cash, Brokerage Cash, ETF, Stock, Fixed Asset, and Other.
- EUR reporting with native values in EUR, USD, GBP, or CHF and dated FX conversion.
- Manual backdated valuations for every asset.
- User-triggered Twelve Data quotes for ETFs and stocks.
- ECB reference rates for conversion to EUR.
- Current portfolio value, tracked cost basis, unrealized P&L, and return.
- Allocation by asset type and asset, portfolio history, and P&L by asset.
- Responsive holdings management with create, edit, value, and archive actions.

Trade lots, realized P&L, tax accounting, transaction-linked balances, automatic schedules,
liabilities, and arbitrary market providers are excluded.

## Asset Semantics

Cash assets contribute to portfolio value and allocation but have no tracked P&L. ETF,
stock, fixed-asset, and other records may carry an acquisition cost and unrealized P&L.
Brokerage cash remains cash, not a security.

An asset stores current identity and position configuration. Valuations are immutable dated
snapshots containing native and EUR value, quantity and cost-basis snapshots, valuation
source, and quote/FX provenance. Editing quantity or cost basis requires an effective date
and replacement valuation so history remains coherent. Assets are archived, never hard
deleted.

Current value is the latest valuation of each active asset. Portfolio history carries each
asset's latest known value forward to month-end points after its acquisition date. Missing
current valuations make the portfolio explicitly incomplete; they are never treated as
zero.

Unrealized P&L is current EUR value minus frozen EUR cost basis. Return is P&L divided by
cost basis when cost basis is positive. Aggregate P&L includes only assets with tracked
cost basis and reports its coverage separately.

## Market Data

The server uses Twelve Data's quote endpoint with a configured symbol and exchange or MIC.
Instrument identity is previewed before confirmation. The API key remains server-side in
`TWELVE_DATA_API_KEY`.

ECB reference rates convert non-EUR quote, valuation, and acquisition values. The latest
available prior business-day rate is used when the requested date has no rate. Manual FX
is allowed only as an explicit fallback and is stored with provenance.

ECB previews are signed by the server and bound to currency, requested date, rate, and
rate date. ECB provenance cannot be submitted without the matching preview token. Twelve
Data quote previews are likewise signed, expire after 24 hours, normalize timestamps to
UTC, and cannot be replayed or persisted after a newer quote.

Refresh is user-triggered. Quote/FX network calls happen in a read-only preview request.
The browser then submits successful normalized previews to a short bulk snapshot write,
so external HTTP does not hold SQLite's request-wide write lock. Failures preserve the
last valid valuation and are reported per asset.

## Persistence

Migration `20260811_0003` adds only new tables. Migration `20260811_0004` adds precision,
FX-provenance, replay, and timezone-safe archive constraints before the first deployment:

- `assets`: identity, type, currency, acquisition date, quantity, cost basis, quote
  configuration, active state, revision, archive date, and timestamps.
- `asset_valuations`: immutable native/EUR valuation and position snapshots with source,
  quote, and FX metadata.
- `asset_events`: append-only asset correction and archival audit.

Money uses integer minor units. Fractional quantities, unit prices, and FX rates use
canonical decimal strings and `Decimal` arithmetic with half-up conversion at money
boundaries. Valuations are indexed by `(asset_id, valued_at)`.

## API

```text
GET    /api/v1/assets
POST   /api/v1/assets
GET    /api/v1/assets/{id}
PATCH  /api/v1/assets/{id}
GET    /api/v1/assets/{id}/valuations
POST   /api/v1/assets/{id}/valuations

GET    /api/v1/portfolio
GET    /api/v1/portfolio/quote-preview
GET    /api/v1/portfolio/fx-preview
POST   /api/v1/portfolio/quote-snapshots
```

Writes use expected revisions and standard problem responses. Asset creation includes an
initial valuation. Quote and ECB snapshots use reviewed, signed preview payloads and the
current asset revision. API responses expose valuation source and as-of/fetched timestamps.

## Page

`/portfolio` contains:

1. Header actions for Add Asset and Refresh Quotes.
2. KPI strip for portfolio value, tracked cost basis, unrealized P&L, and return.
3. Portfolio value and cost-basis history.
4. Allocation by asset type and ranked value by asset.
5. Unrealized P&L by tracked asset.
6. Responsive holdings table/cards with value source and as-of date.
7. A drawer for create, edit, position update, backdated valuation, and archive actions.

Every chart has an exact table. Missing/stale values and quote errors remain visible. The
new route is lazy-loaded and appears in desktop and six-item mobile navigation.

## Testing And Deployment

Backend tests cover migration, decimal precision, asset lifecycle, revision conflicts,
immutable snapshots, EUR conversion, P&L coverage, carry-forward history, quote/FX preview,
partial quote failure, and proof that preview calls do not write.

Frontend tests cover API mapping, empty/loading/error states, conditional asset forms,
manual valuations, quote refresh, archival, chart tables, mobile layout, and stale or
incomplete warnings.

Deployment records ledger revision, transaction count, transfer-tag counts, and SQLite
integrity before migration, then verifies the migrated revision, unchanged ledger rows,
healthy container, and live portfolio API after rebuild.
