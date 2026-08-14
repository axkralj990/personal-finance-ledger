# Transaction Sorting Design

## Goal

Allow users to sort the complete filtered transaction ledger by any displayed data column while
preserving server-side pagination and responsive access to the same sorting behavior.

## API Contract

Extend `GET /api/v1/transactions` with two optional query parameters:

- `sort_by`: `date`, `description`, `account`, `category`, or `amount`.
- `sort_direction`: `asc` or `desc`.

When omitted, the parameters default to `date` and `desc`, preserving the existing newest-first
behavior. FastAPI must reject values outside these allowlists with a `422` response. The API must
not accept arbitrary database column names.

Apply sorting after filters and before offset and limit so the order covers every matching
transaction rather than only the current page. Use these field semantics:

- Date sorts by `transaction_date`.
- Description sorts case-insensitively by description.
- Account sorts case-insensitively by the displayed account name.
- Category sorts case-insensitively by the displayed category name, treating missing categories as
  `Uncategorized`, then by displayed subcategory name.
- Amount sorts numerically by the signed `amount_minor` value.

For Category, apply the subcategory name as a secondary key in the selected direction. For every
field except Date, then apply `transaction_date` descending. Finally apply `created_at` descending
and transaction ID ascending for every field. These deterministic tie-breakers prevent records
with equal primary values from moving unpredictably between pages. No database migration is
required.

## Frontend Behavior

Add `sortBy` and `sortDirection` to the transaction query type and serialize them to the API as
`sort_by` and `sort_direction`. Include both values in the transaction page resource key so every
sort change triggers a server request.

The transaction page owns one sort state, initially `{ sortBy: "date", sortDirection: "desc" }`.
Changing that state resets pagination to page 1 while preserving active filters. Corrections,
deletions, conflict reloads, and manual reloads retain the active sorting.

Make the Date, Description, Account, Category, and Amount desktop headers interactive. Clicking the
active field reverses its direction; clicking another field selects it in ascending order. The
active header displays a direction indicator and exposes `aria-sort="ascending"` or
`aria-sort="descending"`. The action column remains unsortable.

Provide compact sort-field and direction controls with the responsive results so mobile users can
apply every supported sort even though transaction cards have no headers. Keep these controls and
desktop header interactions synchronized through the shared sort state.

## Error Handling

Unsupported sort input is a validation error at the API boundary. A failed sorted request uses the
transaction page's existing error state and retry behavior. Empty sorted results continue to use
the existing filtered and unfiltered empty states.

## Verification

Keep tests focused on the end-to-end contract rather than building a case for every field:

- One backend API test verifies representative signed-amount sorting in both directions before
  pagination and confirms the default remains newest-first.
- One frontend API test verifies serialization of both sort parameters.
- One transaction-page test verifies selecting and reversing a sort, resetting to page 1, and the
  shared responsive controls.

Run backend Ruff and API tests, then the frontend test suite, type checking, lint, and production
build.
