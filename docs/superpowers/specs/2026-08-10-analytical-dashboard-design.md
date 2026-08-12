# Analytical Dashboard Design

## Goal

Replace the compact Overview with one coherent EUR dashboard derived from `main.ipynb`,
`net.ipynb`, and the legacy Dash application. The implementation is read-only with
respect to SQLite: no schema migration, data update, budget storage, index, or currency
change elsewhere in the application.

## Scope

- One read-only `/api/v1/dashboard` response over existing transactions.
- Trailing-12-month default range.
- Inclusive date, category, and dependent subcategory filters.
- Income, spending, net, and monthly spending mean KPIs with prior-range comparisons.
- Week, month, and quarter time series.
- Calendar-period totals and rolling monthly-mean modes.
- Monthly category/subcategory spending composition.
- Ranked taxonomy totals and percentages.
- Jan-Dec year-over-year comparison as grouped monthly bars, one color per year.
- Selected-range cumulative cash flow.
- Accessible chart data tables.
- EUR fixed inside the dashboard, with no dashboard currency selector.

Budgets, targets, true account balance, FX conversion, forecasts, schema changes, and
changes to Import, Manual Entry, Transactions, or other pages are excluded.

## Notebook Mapping

- Monthly expense category stacks become spending composition.
- Food/subcategory analysis generalizes to selected taxonomy.
- Income and net lines become the cash-flow explorer.
- Cumulative “balance” becomes correctly named cumulative cash flow.
- `net.ipynb` monthly signed net becomes the default net series.
- Dash year-over-year month lines become the Jan-Dec comparison.

Embedded notebook outputs, raw tables, hard-coded years, budgets, benchmarks, and model
evaluation are not reproduced.

## Layout

1. Header with data-through date and selected range.
2. Date/category/subcategory filter rail.
3. KPI strip: income, spending, net, monthly spending mean.
4. Cash-flow explorer.
5. Full-width spending composition with ranked spending in a disclosure.
6. Jan-Dec year comparison.
7. Full-width cumulative cash flow.

Desktop follows the existing ledger-studio language. Mobile preserves reading order,
renders only its active chart layout, and exposes a compact data table for every chart.

## Filters

- `date_from` defaults to 12 calendar months before local today.
- `date_to` defaults to local today.
- Invalid or inverted ranges are rejected.
- Category and subcategory support repeated IDs.
- Subcategories must belong to selected categories when category filters exist.
- Category changes remove incompatible subcategories.
- Show all categories clears category and subcategory filters together.
- Filter state lives in URL query parameters.
- Filters apply to every current/prior metric and chart.
- Dashboard currency is always EUR.

The prior comparison range has the same number of calendar days and ends immediately
before `date_from`.

## Financial Semantics

- Income: sum of every positive included amount.
- Spending: positive magnitude of every negative included amount.
- Net: sum of every included signed amount.
- Transaction kind is ignored; historical transfer, refund, and fee values have no special
  reporting semantics.
- Excluded rows are omitted everywhere.
- Composition: negative included amounts only, grouped by their assigned taxonomy.
- Amounts: integer minor units throughout calculations and APIs.
- Cumulative cash flow: selected-range running net starting at zero, never balance.

Monthly spending mean KPI is selected spending divided by the number of calendar months
intersecting the range. Zero-spending months count; partial boundary months count as one
and are marked partial.

## Time Series

Cash-flow controls:

- Measure: Income, Spending, Net.
- Aggregation: Total, Rolling Mean.
- Total grain: Week, Month, Quarter.
- Mean window: Month, Quarter, Year.

In Total mode, weeks start Monday and each point is the measure sum in that calendar
period. Partial periods are flagged and all calendar periods are zero-filled.

In Rolling Mean mode, the control becomes a trailing 1-month, 3-month, or 12-month window.
The chart contains one point per selected date. Each point sums the selected measure over
its trailing window and always reports a monthly mean: divide a Month window by 1, a
Quarter window by 3, and a Year window by 12. Income sums positive amounts, Spending sums
absolute negative amounts, and Net sums signed amounts. A window without matching
transactions is zero. Pre-range transactions are loaded so the first visible window is
complete. Exact data includes window boundaries and the month denominator. Mean mode has
no Week option because a monthly average over one week is not defined by this dashboard.

The response contains calendar totals and all rolling-window series so dropdown changes do
not refetch.

## Year Comparison

- Select Income, Spending, or Net.
- The comparison contains a zero-filled 12-point series per represented year.
- Each year is a separately colored grouped bar series.
- Partial years are labeled without annual aggregate or divided-by-12 cards.

## Composition

Monthly category and subcategory rows contain stable ID, name, period, positive amount,
count, and partial flag. Ranked totals contain amount, count, and percentage of selected
spending. Stable IDs drive consistent colors.
Subcategory colors are deterministically assigned from a broad palette and avoid
collisions among the visible series. Ranked totals are available in a disclosure below
the full-width composition chart.

## Read-Only API

```text
GET /api/v1/dashboard
  ?date_from=YYYY-MM-DD
  &date_to=YYYY-MM-DD
  &category_id=<uuid> repeated
  &subcategory_id=<uuid> repeated
```

Response:

- `meta`: filters, actual data coverage, partial metadata, generated timestamp.
- `summary`: current/prior KPI values and deltas.
- `series`: week/month/quarter totals plus rolling monthly means over 1-month, 3-month, and
  12-month windows for all measures.
- `composition`: monthly taxonomy rows and rankings.
- `annual`: retained API totals, divided-by-12 means, partial flags, and Jan-Dec data;
  the dashboard renders only the Jan-Dec comparison.
- `cumulative`: daily selected-range cumulative net.
- `recent`: retained API data, not rendered on the dashboard.
- `quality`: matching, uncategorized, and category-only counts.

One reporting service owns semantics and period derivation. It selects only required
columns from existing transactions using a normal read-only SQLAlchemy session, then
aggregates the small personal dataset in Python. It performs no flush, commit, DDL, or
side-effecting initialization.

## Interaction And Accessibility

- Rapid URL filter changes ignore stale responses.
- Chart controls switch against the loaded response.
- Empty states identify filters versus absent data.
- Errors retain filters and expose retry.
- Tooltips show exact EUR values.
- Zero/reference lines are named.
- Color is never the only sign/partial indicator.
- Each chart has a textual summary and table alternative.

## Testing

Backend tests cover read-only behavior, EUR filtering, date/taxonomy validation, financial
semantics, zero filling, calendar boundaries, totals, rolling monthly means, partial periods,
prior-range deltas, annual divide-by-12 behavior, cumulative flow, composition, and
response consistency.

Frontend tests cover local trailing-12-month defaults, URL filters, dependent taxonomy,
KPI values, dropdown switching, partial labels, data tables, empty/error states, and
responsive behavior.

Verification records transaction count and SQLite integrity before and after rebuilding.
The count and schema revision must remain unchanged. No migration or backup command is
run as part of this dashboard implementation.
