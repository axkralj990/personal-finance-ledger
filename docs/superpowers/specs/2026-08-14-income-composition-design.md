# Income Composition Design

## Goal

Extend the dashboard's spending composition section to let users inspect income
composition without adding a second large chart. Income composition groups positive
included transaction amounts by their existing assigned category or subcategory.

## User Experience

- Rename the section from `Spending composition` to `Composition`.
- Add an accessible two-button `Spending | Income` toggle in the section heading.
- Keep the existing `Category | Subcategory` toggle.
- Default to Spending so the initial dashboard remains unchanged.
- Switch both controls against the loaded dashboard response without another request.
- Update the section note, chart legend label, ranked table, exact-data disclosure, and
  empty-state copy to match the selected measure and taxonomy level.
- Keep real category names in ranked tables clickable for either measure so they apply
  the existing dashboard category filter.

A two-button toggle is preferred over a select because the dashboard already uses
pressed buttons for binary choices and reserves selects for controls with three or more
options. A second composition section is excluded because it would duplicate the largest
dashboard visualization and lengthen the page.

## Financial Semantics

- Spending composition includes negative amounts and reports their positive magnitudes.
- Income composition includes positive amounts and reports them unchanged.
- Zero amounts belong to neither composition.
- Both measures use assigned transaction taxonomy, regardless of transaction kind.
- Existing date, category, subcategory, currency, and exclusion filters apply equally.
- Uncategorized and category-only transactions retain the existing synthetic identities
  and labels.
- Monthly rows retain count and partial-period metadata.
- Rankings use each measure's selected-range total as their percentage denominator.

## Architecture And API

Replace the composition response's spending-only flat fields with two explicit
breakdowns:

```text
composition:
  spending:
    category_monthly
    subcategory_monthly
    category_ranked
    subcategory_ranked
  income:
    category_monthly
    subcategory_monthly
    category_ranked
    subcategory_ranked
```

The reporting layer introduces a reusable composition-breakdown model and builds one
breakdown per sign. Shared grouping, sorting, percentage, partial-month, and taxonomy
identity logic remains common to both measures. The API schema, frontend types, mapper,
and fixture mirror the nested contract.

The frontend renames `SpendingComposition` to `Composition`. Its local measure and level
state selects one of the four monthly/ranked pairs before passing the rows through the
existing chart transformation. The chart transformation itself remains measure-agnostic
and unchanged.

## Empty And Error States

The dashboard-level loading, request error, retry, and filter behavior remains unchanged.
If the selected measure has no matching rows, the section shows measure-specific empty
copy while retaining both toggles so the user can switch views. Ranked and exact-data
disclosures use the same selected breakdown and do not refetch.

## Accessibility

- Each binary control has a distinct accessible label.
- Buttons expose selection through `aria-pressed`.
- Legend, captions, disclosure labels, amount headings, and empty states name the active
  measure.
- Existing chart accessibility, tooltip formatting, partial-period markers, and exact
  data tables remain available.

## Testing

Backend tests cover:

- Positive, negative, and zero sign assignment.
- Income category and subcategory monthly totals.
- Income rankings, counts, percentages, and ordering.
- Uncategorized and category-only income identities.
- Existing filters and partial-month metadata for both measures.
- Spending behavior remains unchanged.

Frontend tests cover:

- Mapping the nested spending and income API contract.
- Spending remains the default view.
- Switching measure and taxonomy level selects the expected rows.
- Dynamic labels, ranked values, exact data, and measure-specific empty states.
- Category filtering remains available from either ranked measure.

## Scope

This change does not add transaction taxonomy types, new dashboard filters, URL state for
chart controls, database migrations, another endpoint, or separate income-category
rules. It does not change summary, time-series, annual, cumulative, recent, or quality
reporting.
