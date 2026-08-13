# Generic Accounts And Universal Mapping Design

## Goal

Make the single-user self-hosted ledger independent of the owner's banks. Accounts are
database-backed ledger labels selected during import. Every CSV, XLS, and XLSX file uses
one universal inspected-column mapping flow, optionally assisted by OpenAI structured
output. Reporting treats every non-ignored transaction as income or expense by amount
sign only.

## Accounts

`Account` replaces the misleading `SourceAccount` domain name. An account stores a name,
default ISO currency, active state, and timestamps. It has no provider or bank enum.
Selecting an account during import assigns every resulting transaction to that account;
it does not select parsing, mapping, categorization, or sign behavior.

Fresh installations create only `Unknown`. Existing account IDs, names, transaction
relationships, and import relationships remain unchanged during migration, and `Unknown`
is added if absent. The import selector lists active accounts and offers inline account
creation. A separate Accounts page supports creation, rename, and deactivation. Accounts
referenced by ledger history are never physically deleted.

## Universal Mapping

All new CSV, XLS, and XLSX imports use local inspection and one strict Pydantic
`UniversalMappingSpec`. Provider-specific DBS, Revolut, and Mastercard execution profiles
are removed from active import resolution. Existing committed audit records remain
readable but are not executable proposals.

`UniversalMappingSpec` is the sole mapping contract for manual editing, OpenAI structured
output, saved template versions, preview, staging, and deterministic replay. It contains
positional source-column references, canonical date/timestamp/description/amount/currency
targets, explicit date formats, number formats, sign convention, optional hints, and
bounded row filters. Backend validation rejects unavailable columns and invalid internal
combinations before preview or staging.

The signed-amount convention is explicit:

- `EXPENSES_NEGATIVE` preserves every source sign.
- `EXPENSES_POSITIVE` inverts every source sign.

After that transformation, positive amounts are income, negative amounts are expense,
and zero is invalid. Debit/credit source layouts deterministically produce the same signed
canonical amount.

## OpenAI Mapping

OpenAI is optional and configured only through server environment settings, including the
API key, model, enable flag, rate limits, and timeouts. It never runs automatically. The
user clicks **Suggest mapping with OpenAI**, reviews the exact redacted payload and digest,
and explicitly confirms transmission.

The payload contains positional column IDs, headers, inferred local types, inspection
facts, and representative format-preserving samples. Dates preserve enough structure to
infer an explicit format; amounts preserve sign and separators; safe currency and status
values may remain visible. Descriptions, names, references, account numbers, and
identifiers are replaced with placeholders.

The Responses API parses directly into `UniversalMappingSpec` using Pydantic structured
output. The backend then validates all column references and locally previews sample rows.
The result only populates the editable mapping form. No data is staged until the user
confirms the mapping. Refusal, timeout, unavailable configuration, or invalid output falls
back to manual mapping without losing the draft.

## Transaction Semantics

The ledger supports only `INCOME` and `EXPENSE`. Historical and staged `TRANSFER`, `FEE`,
and `REFUND` values migrate by amount sign. No transfer matching or transfer inference is
performed.

Review's **Ignore row** action commits a valid transaction with `is_excluded=true`, an
exclusion reason, and audit timestamps. Ignored transactions remain available through the
originating import audit and participate in duplicate identity, but they never appear in
the normal Transactions page, reporting, category totals, net totals, or model training.
There is no user-facing **Show ignored** control.

## Migration Safety

Before schema changes, stop the application and create a SQLite-consistent timestamped
`.bkp`. Verify integrity, foreign keys, checksum, core row counts, and a temporary restore.
Run the migration first against a copy of production data. Existing transaction, staged,
import, portfolio, and audit rows must remain present. Startup performs foreign-key and
integrity checks after migrations and refuses to serve on failure.

## Verification

Tests cover fresh-install `Unknown`, preservation of existing account IDs, sign-based kind
migration, provider-profile removal, exact sign inversion, ignored-row commit behavior,
OpenAI payload redaction and strict structured output, account CRUD, inline creation,
template replay, production-copy migration, and end-to-end upload through commit. Final
verification includes backend and frontend suites, static checks, production Docker build,
live database counts, and all primary page/API routes.
