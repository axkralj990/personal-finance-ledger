# Portfolio Drawer Simplification Design

## Goal

Make asset setup and valuation understandable without exposing the portfolio storage model.
Each editable field represents one concept, calculated values are not entered twice, and
dated replacement snapshots appear only when a position actually changes.

## Interaction Model

The existing drawer and API remain in place. The frontend adapts the form to the selected
asset type and translates the simplified inputs into the existing asset and valuation
payloads.

ETF and stock setup uses the facts available from a broker confirmation: ticker, exchange,
currency, date bought, number of shares, and purchase price per share. The total purchase
cost is calculated and never entered separately. Bank cash, brokerage cash, fixed assets,
and other assets continue to use one total-value input.

Acquisition cost is optional for non-cash assets. The label is **Total amount paid** and its
help text says that it is the total cost of the currently owned position, including fees if
the user wants fees reflected in P&L. It continues to populate the native and EUR cost-basis
fields required by the API.

## Drawer Modes

### Add Security

- The name field is labeled **Ticker** and is also used as the quote symbol.
- The form asks for exchange, currency, date bought, number of shares, and purchase price
  per share.
- P&L tracking and automatic price updates are always enabled for a new security rather than
  exposed as optional switches.
- The total amount paid is calculated from shares multiplied by purchase price.
- For non-EUR securities, the frontend automatically requests the ECB rate for the purchase
  date. The user does not enter or select purchase FX.
- Saving first creates an immutable purchase-date valuation with the purchase price and cost
  basis. It then automatically uses the existing signed Twelve Data preview and snapshot
  endpoints to save the latest available trading-day quote and show its date.
- Quote failure does not roll back the correctly saved purchase. The drawer closes with a
  warning that the purchase is saved and the current price can be retried.
- Each create attempt carries a client-generated asset ID. Retrying an interrupted request
  returns the same asset instead of creating a duplicate purchase.

### Add Other Asset

- Identity fields remain first.
- Cash asks for a current balance.
- Fixed and other assets ask for an estimated or current total value.
- Optional cost tracking remains available for non-cash, non-security assets.

### Add Valuation

- Securities with a quantity ask for date and price per share, then show the calculated
  total value.
- Assets without a quantity ask for date and total value.
- The form does not expose both editable unit price and editable total value.

### Edit Asset

Name and quote settings remain editable. Asset type, date bought, number of shares, and
purchase price are fixed after creation so an edit cannot silently rewrite historical
allocation or invent a present-day value. Existing securities derive their displayed
purchase price from saved quantity and native cost. An incorrect purchase is archived and
added again with the correct facts.

The latest saved price or total value pre-fills dated value forms. Existing securities that
have a quantity but no stored unit price derive a display price from the latest native value
for convenience.

## Currency Conversion

EUR assets need no currency controls. For non-EUR values, the primary action is **Use ECB
rate** and the calculated EUR amount is shown beside the native amount. Raw rate and rate
date inputs are hidden under **Enter a rate manually**. Manual controls open automatically
when editing existing data with manual provenance.

Cost conversion and valuation conversion remain separate because they apply on different
dates. Security purchase conversion is automatic and always requests the date bought. Manual
valuation conversion retains its explicit ECB/manual fallback. Existing signed ECB preview
and provenance requirements are unchanged.

## Validation And Errors

- Quantity and price per share must be positive canonical decimals.
- Total money inputs retain the existing two-decimal minor-unit limit.
- Calculated totals use the existing exact decimal multiplication and half-up rounding.
- A position change requires a date and a value after the change.
- Validation messages use visible labels such as **Price per share** and **Total amount
  paid**, not storage terms such as native value or cost basis.
- Existing revision-conflict, ECB-token, safe-range, and API problem handling remains.

## Accessibility And Responsive Behavior

Calculated totals use live text that remains readable without relying on color. Conditional
sections enter the normal document flow and preserve associated labels. The existing drawer,
keyboard behavior, focus treatment, and responsive form grid remain unchanged. Progressive
disclosure reduces the initial field count on both desktop and mobile.

## Compatibility

The asset API rejects asset-type changes and security purchase changes after creation so
historical allocation and P&L semantics cannot be rewritten. Asset creation accepts an
optional client-generated ID for idempotent retries. Historical valuations remain immutable.
The Yahoo fallback adds one valuation-source enum value and widens quote-preview source
contracts without changing existing rows.

## Market Data Fallback

Twelve Data remains the preferred market-data provider. Some ordinary international ETFs
are restricted to paid Twelve Data plans even though their reference records are visible.
When Twelve Data cannot return a configured instrument, the server attempts Yahoo Finance
for exchanges with an explicit symbol mapping. The initial fallback covers LSE (`.L`), the
exchange required by the current CSPX holding. Unknown exchanges fail rather than guessing
an instrument; additional exchanges can be added only with provider identity tests.

Yahoo responses are validated against the configured native currency and expected Yahoo
exchange identity. The latest non-null chart price and its trading date are used. The
provider request time remains separate from the market date. Future-dated quotes are
rejected.

Yahoo snapshots use a distinct `YAHOO_FINANCE` valuation source in storage, signed previews,
API responses, and the UI. They are never labeled as Twelve Data. Both providers share the
existing ECB conversion, review token, replay protection, and atomic snapshot persistence.
If both providers fail, the combined error remains visible and P&L stays unavailable instead
of becoming zero.

## Historical Market Curves

Quoted securities backfill completed calendar months from the acquisition month through the
last completed month. Yahoo monthly closes become month-end `YAHOO_FINANCE` valuations; the
current incomplete month continues to use the independently fetched live quote. The original
purchase snapshot remains intact.

Each historical price is converted with the latest ECB reference rate available on or before
that calendar month end. ECB observations are fetched as one date range and resolved locally.
Historical provider results with a currency or instrument mismatch are rejected. A reported
split after acquisition blocks automatic backfill because fixed quantity would make the
pre-split value inaccurate.

History preview and persistence remain two signed steps. One preview contains every missing
month for one asset, all with the same provider fetch timestamp and distinct valuation dates.
Replay uniqueness therefore covers asset, source, fetch timestamp, and valuation date.
Persistence skips provider/month combinations already stored so retries fill gaps without
duplicating history.

The main graph offers two views: aggregate portfolio history and a selected asset performance
curve. The aggregate uses persisted month-end values plus the current as-of point. The asset
curve plots persisted market value, frozen cost basis, and unrealized P&L. Manual and cash
values remain explicitly marked as carried when no newer snapshot exists.

## Testing

Frontend tests will verify:

- Security purchase totals are calculated from quantity and purchase price per share.
- Security creation submits a purchase-date cost and valuation using automatic historical
  ECB evidence.
- A successful creation automatically previews and saves today's signed quote.
- Quote failure preserves the created purchase and produces a retryable warning.
- Total value is not an editable duplicate for quantity-based securities.
- Cash, fixed assets, and other assets use one total-value field.
- Position-change controls stay hidden during identity-only edits.
- Security purchase and type controls become read-only after creation.
- Existing assets without a stored unit price retain a usable fallback.
- ECB and manual FX progressive disclosure submit unchanged provenance payloads.
- Archive, quote refresh, reset, error, and responsive behavior continue to pass.
