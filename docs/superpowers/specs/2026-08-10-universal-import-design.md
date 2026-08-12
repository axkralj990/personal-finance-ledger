# Universal Tabular Import Design

## Goal

Replace provider-specific import entry points with one reliable CSV/XLS/XLSX workflow
that can inspect unknown tables, suggest a canonical column mapping through layered
inference, let the user correct that mapping, and then reuse the existing tagging,
duplicate review, and transactional commit pipeline.

The feature is ledger-first. Its purpose is to reduce import friction without weakening
data provenance, deterministic parsing, privacy, or user control.

## Scope

The first release supports:

- One primary import entry point for CSV, XLS, and XLSX files.
- Local file inspection and tabular structure detection.
- Mapping reuse through exact structural signatures.
- Existing provider adapters as predefined profiles.
- OpenAI-assisted mapping for unknown structures using headers and redacted samples.
- Manual mapping when no suggestion is available or correct.
- Guided date, amount, number, sign, constant, and row-filter transformations.
- Deterministic full-file parsing into the existing staged transaction contract.
- Existing category/subcategory tagging, duplicate detection, review, and commit.
- Versioned mapping templates and an immutable per-batch execution-plan snapshot.

Accepted generic input is one rectangular table per selected sheet, one header row, and
one transaction per data row. The table may not require merged semantic cells,
continuation rows, cross-row derivation, or multiple independent tables in one sheet.
Files outside this envelope require an adapter-backed predefined profile.

The release does not add canonical transaction fields, arbitrary expressions, fuzzy
template matching, per-row LLM transformation, LLM category assignment, bank API sync,
budgets, forecasts, or account reconciliation.

## Principles

1. The LLM proposes a guided mapping recipe; it never converts transaction rows.
2. The user can inspect and change every proposed mapping before staging.
3. All rows are transformed locally and deterministically from a validated specification.
4. Known formats, saved mappings, and manual mapping continue to work without OpenAI.
5. Raw source files and rows remain available for audit.
6. Destination account, institution metadata, and input execution profile are independent
   concepts.
7. No external call runs while a SQLite transaction or application write lock is held.

## User Flow

### 1. Select And Inspect

The user chooses a destination ledger account and uploads one CSV, XLS, or XLSX file.
Account selection determines where committed transactions belong; it does not select the
parser.

The server retains the original file and inspects it locally. Inspection detects:

- File type and workbook sheets.
- Text encoding, delimiter, and quoting for CSV.
- Candidate header row and data bounds.
- Normalized column names and inferred value types.
- Representative rows for preview and mapping inference.
- Row count, blank rows, exact repeated-header rows, and possible footer rows for user
  review.

Existing configured upload-byte and row limits remain in force. Inspection additionally
limits workbooks to 32 sheets, 256 columns per selected table, 5,000,000 inspected cells,
and 100 MiB of uncompressed workbook content. Format is verified from content rather than
filename alone. Formulas are read only from cached values and never evaluated; macros,
external links, data connections, encrypted workbooks, malformed archives, and workbook
content over these limits are rejected.

If sheet or header detection is ambiguous, the user chooses them before inference. The
raw preview updates immediately.

### 2. Resolve A Mapping

Mapping resolution uses this strict order:

1. Active confirmed mapping with an exact structural signature match.
2. Predefined provider profile recognized from the inspected structure.
3. OpenAI suggestion, only after the user approves the displayed redacted payload.
4. Empty manual mapping when the other options do not produce a valid result.

Every route leads to the same mapping screen. Reused and predefined mappings populate
controls but never bypass confirmation.

### 3. Map And Validate

The mapping screen places canonical field controls beside raw and parsed previews. Each
source dropdown selects the suggestion by default. Its first option is labeled with the
proposal, such as `Suggested: Datum bremenitve`; remaining options include other source
columns, supported derived values, constants, and `Not mapped` where optional.

The screen reports structural confidence from actual sample validation, not from an LLM
self-assessment. Every edit recalculates parsed values, valid/error row counts, and field
diagnostics.

The user can name and save the confirmed mapping. Continuing applies the mapping to the
full file locally. Full-file errors are shown before any transaction review begins.

### 4. Classify And Review

Successfully mapped rows enter the existing pipeline:

1. Normalize canonical values.
2. Detect exact and likely duplicates.
3. Apply existing account and global tag rules, plus provider rules only when the selected
   adapter-backed profile declares that provider.
4. Apply the active local category/subcategory model.
5. Present unresolved rows in the existing Import Review workflow.
6. Commit included rows in one database transaction.

The OpenAI mapping request does not assign personal categories. Source category and
subcategory columns are optional hints. They are accepted only when they resolve exactly
to active managed taxonomy with a valid parent relationship; otherwise normal tagging and
review decide the labels.

## Canonical Mapping Specification

An immutable `ImportExecutionPlan` is a discriminated union of `GuidedMappingSpec` and
`AdapterProfileRef`. `GuidedMappingSpec` is a strict, versioned Pydantic model shared by
confirmed templates, OpenAI structured output, manual mappings, and predefined profiles
that fit the guided transform set. `AdapterProfileRef` captures adapter/profile ID,
version, and non-sensitive configuration for formats requiring custom behavior. Every
batch snapshots one complete execution plan for deterministic replay.

Canonical targets are limited to the current ledger model:

- `transaction_date`: required source column and date parsing configuration.
- `transaction_timestamp`: optional source column and timestamp parsing configuration.
- `description`: required source column and normalization configuration.
- `amount`: required signed source column or debit/credit derivation.
- `currency`: required source column or ISO currency constant.
- `source_native_id`: optional source column.
- `category_hint`: optional source column.
- `subcategory_hint`: optional source column.

Supported guided transforms are deliberately finite:

- Explicit date format, day-first choice, and timezone where a timestamp exists.
- Decimal separator, thousands separator, and surrounding currency-symbol removal.
- Signed amount with optional sign inversion.
- Separate debit and credit columns combined into one signed amount.
- Constant currency.
- Row inclusion/exclusion by exact status value.
- Empty-row and exact repeated-header removal.
- Footer removal only through a user-confirmed exact normalized marker/value rule.

Operations run in this order: row-bound filtering, source extraction, blank handling,
number/date parsing, amount derivation, sign transformation, taxonomy-hint resolution,
then canonical validation. When both debit and credit are
populated, or either contains a sign contrary to its configured convention, the row is an
error. Parentheses and trailing-minus values are supported only when explicitly enabled.
Filters contain an explicit set of normalized values; a blank matches only when included.

When a timestamp is mapped, `transaction_date` may be omitted and is derived in the
configured timezone. If both are mapped, a date that differs from the timestamp-derived
date is a row error. Hidden kind metadata is derived as `EXPENSE` for negative amounts and
`INCOME` for positive amounts. It is not mapped, displayed, or used for reporting. Zero
amounts are invalid.

Arbitrary code, regular-expression replacement, formulas, and chained expression builders
are excluded. Files needing behavior outside the guided specification continue through an
adapter-backed predefined profile.

Validation rejects a specification when:

- A required target has no source or constant.
- A referenced source column does not exist.
- Amount/date settings are internally inconsistent.
- Debit and credit mapping references the same column.
- Currency constants are not three-letter ISO codes.
- Category and subcategory hint configuration violates its dependency.

These are structural specification errors. Sample parse failures are preview diagnostics,
not specification errors. Bounded full-file validation determines whether at least one row
is importable and reports all row-level conversion failures.

## Structural Signatures And Templates

A structural signature is derived from versioned inspection rules, positional immutable
column IDs, normalized raw labels, column order, selected sheet/header location, and the
execution-plan schema version. Inferred sample types are displayed as diagnostics but do
not affect identity. The signature does not include filenames, account numbers,
descriptions, amounts, or other row values. Duplicate or blank labels remain unambiguous
because plans reference positional column IDs rather than labels.

Exact matches may propose a saved template. Account-scoped matches take precedence over
global matches; multiple matches at the same scope require user selection. Near matches do
not auto-apply in the first release. A user can still select an existing template manually
and must resolve any missing columns before continuing.

`ImportMappingTemplate` stores:

- Stable ID and human-readable name.
- Structural signature and optional destination-account scope.
- Versioned import execution plan.
- Origin: `PREDEFINED`, `LLM_CONFIRMED`, or `MANUAL`.
- Active state, creation/update timestamps, and revision.

Editing a template creates a new version. Existing batches retain the exact snapshot they
used. Templates are never physically deleted through the API: `active=false` prevents
future proposals while retaining every version referenced by audit history. Predefined
templates cannot be edited or deactivated.

Predefined formats may initially remain adapter-backed where their behavior cannot be
represented by guided transforms. They still appear in the unified wizard. The user may
accept the predefined profile or switch to a generic editable mapping. Adapter-backed
plans retain the adapter's existing native-ID and fingerprint behavior.

Generic plans use fingerprint algorithm `generic-row-v1`: hash the structural signature,
the normalization version, and every normalized non-empty source cell identified by its
positional column ID. The fingerprint is independent of mapping choices, so remapping does
not change duplicate identity. A mapped native ID remains the strongest exact identity.
Files whose exports change volatile raw columns may fall back to existing likely-duplicate
review rather than being silently treated as exact duplicates.

## OpenAI Boundary

The server uses the OpenAI Responses API with Pydantic structured output matching
`GuidedMappingSpec`. The API key, model name, timeout, and retry limit are server
environment settings. The key is never sent to or stored by the browser or database.
Inference is disabled unless both a key and `OPENAI_MAPPING_ENABLED=true` are configured.
The default limit is one concurrent request and ten requests per rolling hour, with lower
deployment-specific limits allowed.

The outbound request contains only:

- Canonical field definitions and allowed transformations.
- Normalized source headers.
- Locally inferred column types.
- At most 12 representative, locally tokenized rows selected deterministically from the
  beginning, middle, and end of non-empty data.
- Non-sensitive inspection facts needed to interpret the table.

Every cell is treated as sensitive. Outbound values follow an allowlist: ISO currency
codes and the normalized status words `completed`, `pending`, `reverted`, `reversed`,
`cancelled`, and `declined` may remain literal; dates become format tokens; numbers become
sign, decimal, and grouping-pattern tokens; identifiers become
`<IDENTIFIER>`; and all other text becomes `<TEXT>`. IBAN/account/card patterns, emails,
names, merchant text, descriptions, and free-form categories are never sent as values.
Headers are sent verbatim because they are the mapping subject, and the UI warns that a
header itself may contain sensitive text.

`GET /imports/{id}/mapping-suggestion-payload` returns the complete payload that would be
sent plus a server-generated SHA-256 digest and batch revision. Every suggestion request,
not only the first, must include that digest, the expected revision, and explicit consent.
The server regenerates the payload and rejects a digest/revision mismatch. The stored
audit records consent timestamp and digest.

The application stores the selected model, OpenAI request ID, mapping prompt/schema
version, payload digest, consent time, timing, outcome, and parsed execution plan.
It does not store the outbound sample payload, raw model response, API key, or sensitive
response bodies. Mapping plans and request metadata are sensitive ledger data and follow
the same backup and deletion policy as import batches. Application logs contain batch IDs,
timing, statuses, and error classes only. Deployment documentation requires the lowest
available provider retention/data-use setting and states the configured policy.
Retained source files, raw rows, and mapping templates keep the existing local import
retention behavior; this feature introduces no additional cloud copy or automatic purge.

Calls default to a 5-second connection timeout, 20-second read timeout, 30-second overall
budget, and at most one retry for connection failures, `429`, or `5xx`, honoring
`Retry-After` within the overall budget. Authentication, permission, connection, timeout,
rate-limit, refusal, status, and structured-output validation errors all degrade to manual
mapping.

Because the application has no authentication, inference endpoints accept same-origin
JSON requests only, validate `Origin` and `Host`, reject browser form submissions, and use
the global concurrency/rate limits above. These controls reduce accidental or drive-by LAN
use but do not make direct internet exposure safe.

## Persistence And Lifecycle

An import batch stores inspection metadata, mapping state, mapping revision, source
template ID, immutable confirmed execution-plan snapshot, input profile/provider identity,
fingerprint algorithm/version, and optional OpenAI audit metadata. Provider on the
destination account remains institution metadata. Generic plans have no provider scope and
skip provider-scoped tag rules; adapter-backed plans use their explicit profile provider.
Account and global tag rules continue to apply in both cases.

Allowed lifecycle transitions are:

| From | To | Condition |
| --- | --- | --- |
| `UPLOADED` | `AWAITING_MAPPING` | Local inspection succeeds or needs user choices. |
| `UPLOADED` | `FAILED` | File is unreadable, unsafe, or outside hard limits. |
| `AWAITING_MAPPING` | `STAGING` | A structurally valid plan is confirmed. |
| `STAGING` | `NEEDS_REVIEW` | Rows are staged and any row needs user action. |
| `STAGING` | `READY` | All staged rows are committable or explicitly non-ledger audit rows. |
| `STAGING` | `AWAITING_MAPPING` | Fatal file/plan failure stages no rows. |
| `NEEDS_REVIEW` or `READY` | `AWAITING_MAPPING` | User confirms remapping and discarding staged edits. |
| `NEEDS_REVIEW` | `READY` | Review resolves every pending row. |
| `READY` | `COMMITTED` | Transactional preflight and insert succeed. |
| Any nonterminal state | `DELETED` | User deletes the draft. |

`COMMITTED`, `FAILED`, and `DELETED` are terminal. `STAGING` is persisted before full-file
conversion so interrupted work is visible. Staging uses a temporary in-memory result and
one atomic staged-row replacement transaction. On startup, an abandoned `STAGING` batch is
reset to `AWAITING_MAPPING` with a retryable interruption diagnostic; partial staged rows
from the abandoned revision cannot exist.

Any nonterminal batch except active `STAGING` can return to `AWAITING_MAPPING`. If staged
rows already exist, the UI explicitly warns that restaging will replace those rows and
discard row-level review edits. Confirmed restaging increments the mapping revision and
applies the new snapshot. Committed batches are immutable.

Existing duplicate-file protection remains account-scoped. When the same file already has
an uncommitted batch, the UI opens that draft instead of requiring another upload. A
committed duplicate remains blocked.

External inference is split from persistence:

1. Persist upload and inspection in a short write phase.
2. Release the database transaction and application write lock.
3. Call OpenAI.
4. Persist the validated suggestion in a second short write phase if the batch revision
   still matches.

A stale response is discarded rather than overwriting a newer inspection or mapping.

`POST /stage` atomically stores one `StagedTransaction` for every source data row. Row-level
conversion failures retain raw data and diagnostics, use `PENDING`, and force
`NEEDS_REVIEW`. Fatal container/file errors or a plan that yields no importable rows stage
nothing and return the batch to `AWAITING_MAPPING`. No staging operation inserts committed
ledger transactions.

## API Surface

The existing import API changes from immediate provider-driven staging to explicit
inspection, mapping, and staging:

```text
POST   /api/v1/imports
GET    /api/v1/imports/{id}
GET    /api/v1/imports/{id}/source-file
GET    /api/v1/imports/{id}/inspection
PATCH  /api/v1/imports/{id}/inspection
GET    /api/v1/imports/{id}/mapping-suggestion-payload
POST   /api/v1/imports/{id}/mapping-suggestion
POST   /api/v1/imports/{id}/mapping-preview
PUT    /api/v1/imports/{id}/mapping
POST   /api/v1/imports/{id}/stage
GET    /api/v1/imports/{id}/rows
PATCH  /api/v1/imports/{id}/rows
POST   /api/v1/imports/{id}/commit
DELETE /api/v1/imports/{id}

GET    /api/v1/import-mappings
POST   /api/v1/import-mappings
GET    /api/v1/import-mappings/{id}
PATCH  /api/v1/import-mappings/{id}
```

`POST /imports` retains the upload, creates the draft, and runs only local inspection.
`POST /mapping-suggestion` is logically read-only during the external call and must not be
wrapped by the current request-wide SQLite write lock. Its final conditional persistence
uses a short lock and optimistic batch revision.

`PATCH /inspection` changes sheet/header choices and reinspects using `expected_revision`.
Raw previews are bounded to 100 rows per request and use positional offsets. Source-file
download returns the retained original only for non-deleted batches.

`POST /mapping-preview` validates and previews a candidate plan without persistence or
staged rows. `PUT /mapping` confirms one plan with optimistic batch revision. Template
creation is a separate `POST /import-mappings`; `PATCH` renames, versions, or deactivates a
user template. `POST /stage` performs full-file mapping, stores the immutable plan
snapshot, and enters the existing review pipeline.

All state-changing requests include `expected_revision`. Mapping suggestion additionally
includes the reviewed payload digest and explicit consent. Template and batch revisions
are independent.

Errors continue to use the application's problem response with machine code, message,
field/row location where available, recoverability, and current batch revision.

## Frontend Behavior

The primary Import page contains one upload action and the following steps:

1. `Select`: destination account and file.
2. `Inspect`: sheet/header choice and raw table preview when ambiguous.
3. `Map`: canonical dropdowns, guided transforms, parsed preview, and validation summary.
4. `Review`: existing category, duplicate, and validation workflow.
5. `Commit`: existing explicit commit summary and action.

The interface distinguishes suggestion origin with text: saved mapping, predefined
profile, OpenAI suggestion, or manual. Color is not the only indicator.

Loading and recovery states cover upload, local inspection, remote suggestion, preview
validation, full-file staging, stale revisions, network/API failure, and restart recovery.
The mapping screen remains usable while OpenAI is unavailable. Mobile uses field cards and
a horizontally scrollable preview rather than reproducing a dense desktop grid.

## Failure Handling

- Unsupported or ambiguous structure retains the draft and exposes manual sheet/header
  controls.
- Invalid OpenAI output is never partially applied.
- OpenAI failure leaves the current mapping untouched and enables manual mapping.
- Sample-valid but full-file-invalid mappings return aggregate and per-row diagnostics
  without committing transactions.
- Mapping edits invalidate prior parsed previews.
- Staging interruption leaves a recoverable batch and never mixes two mapping revisions.
- Template revision conflicts return `409` and preserve the user's local edits.
- Known adapter errors retain their existing row-level audit behavior.
- No inference failure can block access to retained source files or draft deletion.

## Testing

Backend unit tests cover:

- CSV encoding, delimiter, quoting, header, and data-bound detection.
- Workbook sheet/header detection.
- Input-envelope enforcement, workbook archive limits, and rejection of unsafe workbook
  features.
- Structural signatures and exact template matching.
- Redaction and bounded representative sampling.
- Strict mapping validation and every guided transform.
- Deterministic parsing and stable fingerprints.
- Transaction timestamp/date derivation and signed amount behavior.
- Source taxonomy hint resolution.

Backend contract and integration tests cover:

- Mocked OpenAI structured output and all documented fallback errors.
- Proof that non-allowlisted cell values do not enter outbound payloads and that outbound
  sample payloads or sensitive error bodies do not enter persistence or logs.
- Payload digest/revision mismatch, same-origin enforcement, rate limiting, and disabled
  inference configuration.
- Upload, inspect, suggest, preview, stage, review, and commit.
- Saved/predefined mapping proposal order.
- Remap confirmation, staged-row replacement, and revision conflicts.
- Draft recovery across process restarts.
- Duplicate file and transaction behavior.
- Regression fixtures for Revolut, DBS, Mastercard, legacy, and manual imports.
- No database transaction or application write lock held during the external call.

Frontend tests cover:

- Suggested dropdown defaults and alternative selection.
- Raw/parsed preview synchronization.
- Date, amount, sign, constant, and filter controls.
- OpenAI consent and exact outbound-payload disclosure.
- Manual fallback for absent configuration and API failures.
- Invalid mapping and full-file error summaries.
- Template naming, reuse, version conflict, and deactivation.
- Keyboard navigation, narrow screens, reload, and draft recovery.

## Delivery Order

1. Mapping models, inspection contract, and deterministic guided mapper.
2. Persistent mapping templates and batch lifecycle migration.
3. Unified upload, inspection, mapping, preview, and manual fallback UI.
4. Existing adapters exposed as predefined profiles.
5. OpenAI structured-output integration, redaction, consent, and audit metadata.
6. Restaging, template management, recovery states, and complete regression coverage.

The feature is complete when every current provider fixture can pass through the unified
entry point, an unknown anonymized statement can be mapped without code changes, OpenAI
can be removed or disabled without breaking imports, and committed transaction semantics
remain identical to the current reviewed import pipeline.
