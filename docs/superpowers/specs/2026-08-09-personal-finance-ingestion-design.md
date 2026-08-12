# Personal Finance Ingestion Design

## Goal

Replace the notebook-driven CSV workflow and read-only Dash prototype with a private,
self-hosted application for importing, reviewing, classifying, storing, and analyzing
personal transactions. The first deployment runs on Synology Container Manager and
migrates the existing transaction history into the new ledger.

## Scope

The first usable release supports:

- Revolut, DBS, and Mastercard statement uploads, one file per import batch.
- Quick and bulk manual transaction entry.
- Persistent import drafts and retained original files and raw rows.
- Automatic category and subcategory proposals with confidence.
- Editable review, ignored-row decisions, and hierarchical category validation.
- Exact duplicate blocking and explicit review of likely duplicates.
- A managed category and subcategory hierarchy.
- Searchable transactions and currency-safe dashboards.
- Migration of the existing labeled history.
- A single private user on a LAN or VPN, without application authentication.
- A single Docker container and a persistent SQLite volume.

## Architecture

The application is a modular monolith. A React and TypeScript SPA built with Vite and
Tailwind communicates with a versioned FastAPI API. A multi-stage image compiles the SPA
and copies its static output into the Python runtime, where FastAPI serves both the SPA
and `/api/v1`.

Backend modules are organized by domain:

- `imports`: files, batch state, staged rows, review changes, and commit orchestration.
- `sources`: provider-specific parsing and canonical normalization.
- `duplicates`: exact identity and explainable likely-match scoring.
- `tagging`: correction rules, model loading, prediction, and model metadata.
- `taxonomy`: managed categories and parent-constrained subcategories.
- `transactions`: committed ledger records, corrections, exclusions, and queries.
- `reporting`: currency-safe dashboard aggregations.
- `database`: SQLAlchemy models, repositories, sessions, and Alembic migrations.

Pydantic v2 validates API and file boundaries. Internal parsing structures use standard
dataclasses where validation is unnecessary. SQLAlchemy 2 owns persistence. SQLite uses
foreign keys, WAL mode, a busy timeout, and short transactions.

## Storage Model

Core entities are:

- `source_accounts`: provider, display name, default currency, and active state.
- `categories`: stable identity, display name, sort order, and active state.
- `subcategories`: stable identity, parent category, display name, and active state.
- `import_batches`: account, filename, retained-file path, file hash, parser version,
  status, counts, errors, and timestamps.
- `staged_transactions`: raw row, normalized fields, source identity, fingerprint,
  transaction kind, prediction, confidence, accepted labels, validation issues,
  duplicate state, ignore decision, row number, and revision.
- `transactions`: signed amount in minor units, ISO currency, source account, date and
  optional timestamp, description, kind, accepted taxonomy, source identity,
  fingerprint, originating batch and staged row, exclusion state, and timestamps.
- `tag_rules`: normalized-description match, scope, category, subcategory, and state.
- `model_versions`: artifact path, checksum, training metadata, taxonomy version, and
  activation state.
- `transaction_events`: append-only correction and exclusion audit records.
- `transaction_deletions`: detached tombstones containing only the removed transaction
  ID, deletion reason, and timestamp so permanent deletion remains minimally auditable.

Transaction kinds `EXPENSE`, `INCOME`, `REFUND`, `FEE`, and `TRANSFER` may remain on
historical rows as hidden source metadata. Kind has no reporting, inclusion, or user-facing
special-handling semantics. Every included positive amount is income, every included
negative amount contributes its magnitude to spending, and every included signed amount
contributes to net flow. Ignored staged rows and excluded committed rows are omitted.
Reverted source rows remain in the import audit and do not create ledger transactions.

Users classify transactions only with Category and Subcategory. New manual and parsed
rows derive `INCOME` from a positive amount and `EXPENSE` from a negative amount. Manual
entry and review expose no kind control or badge.

Original currencies are preserved and no exchange-rate conversion occurs in the first
release. Reports require one currency before aggregating monetary values.

## Import Lifecycle

Batch states are `UPLOADED`, `PARSED`, `NEEDS_REVIEW`, `READY`, `COMMITTED`, `FAILED`,
and `DELETED`.

1. The user selects a source account and uploads one statement file.
2. The server streams the file to `/data/uploads`, enforces limits, calculates a hash,
   and records a batch.
3. The source adapter validates the file schema and converts each row to a canonical
   staged transaction while retaining the raw row.
4. Exact duplicate detection checks duplicate files, provider-native IDs, and
   provider-specific stable fingerprints. Exact duplicates are blocked.
5. Likely duplicate detection requires account, currency, and signed amount equality,
   then scores date proximity and normalized description similarity. The user must
   decide whether to keep or ignore every likely match.
6. Tagging applies account-specific rules, provider rules, global rules, then the active
   ML model. Low-confidence output remains unresolved.
7. Review edits autosave with optimistic revision checks. Category selection restricts
   the available subcategories. Corrections create future rules only when the user
   explicitly selects `Remember this correction`.
8. Commit repeats validation and duplicate checks inside one database transaction. It
   inserts accepted rows, records requested rules, and marks the batch committed. Any
   failure rolls back the entire commit.

Ignored rows and their reasons remain attached to the batch but never become ledger
transactions. Draft batches survive browser and container restarts and are globally
visible to the single user. Stale browser writes return a conflict rather than silently
overwriting newer changes.

### Mastercard Mapping

Mastercard accepts CSV, XLS, and XLSX exports with the Slovenian columns `Prodajno mesto`,
`Št. kartice`, `Datum plačila`, `Znesek`, `Valuta`, `Originalna valuta`,
`Datum bremenitve`, and `Obroki`. The ledger date is `Datum bremenitve`, falling back to
`Datum plačila` only when the debit date is absent. Every row is stored as an expense with
`-abs(Znesek)`. The parser preserves all source fields, ignores empty trailing columns,
and derives a stable source identity from masked card, merchant, purchase/debit dates,
amount, currency, and installment number so equivalent spreadsheet and CSV exports
deduplicate consistently.

## Historical Migration

Existing finalized CSV data is loaded through a dedicated legacy source adapter and an
audited migration batch. The migration preserves every original value in raw metadata.
Known source spelling and casing differences and taxonomy aliases are normalized through
an explicit mapping. Conflicting labels, unknown taxonomy values, and existing duplicate
candidates are staged for review rather than silently rewritten or discarded.

The migration is idempotent: the source file hash and deterministic row fingerprints
prevent a second run from inserting the same history.

## Tagging

The first prediction layer uses exact normalized-description rules learned from approved
corrections. Model training is an explicit command, never an HTTP request. It extracts
the existing notebook approach into reproducible Python code, fixes random seeds, stores
the complete scikit-learn pipeline and metadata, and activates artifacts explicitly.

Category is predicted first. Subcategory prediction is constrained to the selected or
predicted parent category. Confidence and model version are retained with every staged
proposal. A missing or incompatible model degrades to rules and manual review instead
of failing an import.

Review displays lower-confidence predictions as suggested Category and Subcategory
values instead of presenting them as uncategorized. Accepting a suggestion copies both
labels atomically into the accepted fields; duplicate and validation decisions remain
independent. Only predictions above the configured thresholds are accepted automatically.

## Frontend

Primary routes are:

- `Overview`: currency and date filters, income, spending, net flow, trends, category
  distribution, account breakdown, and recent transactions.
- `Transactions`: paginated server queries, correction, exclusion, permanent deletion,
  and import lineage. Deletion requires the current revision and explicit confirmation,
  removes duplicate identities so the source row may be imported again, and retains only
  a detached non-sensitive tombstone.
- `Import`: source/file selection, parse summary, review, commit, drafts, and history.
- `Manual Entry`: quick entry and bulk grid tabs.
- `Categories`: hierarchy, active state, and correction rules.

AG Grid Community is used for bounded import-review and manual-entry datasets. The design
does not depend on Enterprise-only server-side row models, range selection, clipboard,
or batch-editing features. Ledger pagination is API-driven. Grid routes are lazy-loaded
and receive explicit ledger-studio theme tokens.

The visual direction is ledger studio: warm paper surfaces, charcoal ink, restrained
forest-green accents, accessible rust and green states, tabular numerals, editorial
headings, quiet chart grids, and minimal purposeful motion. Desktop uses compact left
navigation. Mobile uses bottom navigation plus card/detail presentations where a dense
grid is unsuitable.

Every workflow defines loading, empty, filtered-empty, parsing, saving, saved, validation
failure, API failure, stale revision, retry, and destructive-confirmation states. Bulk
actions state whether they affect selected visible rows or all currently filtered rows.
Import Review provides `Include selected`; it applies visible suggestions atomically,
clears ignore reasons, and includes only selected valid rows. Invalid rows remain pending
with their validation errors.

Committed transaction correction includes signed amount editing in the existing currency.
Amounts are parsed exactly to minor units, cannot be zero, use optimistic revision checks,
and write old/new values to the correction audit. Changing an amount derives the hidden
`INCOME` or `EXPENSE` metadata from its sign.
Original provider identities remain unchanged for reliable reimport deduplication.

Transactions and Import Review both support case-insensitive description search. Import
Review combines local description search with status filters, and bulk actions continue
to apply only to selected rows visible under both filters.

## API Surface

Principal endpoints are:

```text
POST   /api/v1/imports
GET    /api/v1/imports
GET    /api/v1/imports/{id}
GET    /api/v1/imports/{id}/rows
PATCH  /api/v1/imports/{id}/rows
POST   /api/v1/imports/{id}/commit
DELETE /api/v1/imports/{id}

GET    /api/v1/transactions
PATCH  /api/v1/transactions/{id}
POST   /api/v1/manual-imports

GET/POST/PATCH /api/v1/categories
GET/POST/PATCH /api/v1/tag-rules
GET             /api/v1/reports/*
GET             /health
```

Errors use a consistent problem response with a machine code, message, affected field or
row, and recoverability. Revision conflicts return `409`; malformed requests return
`422`. Files are parsed synchronously under a configured size and row limit, avoiding a
queue and worker service for the initial personal workload.

## Testing

- Parser contract tests use small anonymized fixtures for every supported source variant.
- Unit tests cover normalization, amount signs, transaction kinds, taxonomy, rule
  precedence, confidence thresholds, and duplicate boundaries.
- Integration tests use temporary SQLite databases for migrations, draft recovery, file
  idempotency, row revisions, rollback, and commit.
- Frontend tests cover editable cells, dependent taxonomy, validation, and page states.
- Playwright tests cover upload, duplicate review, correction rules, ignore, commit,
  quick entry, bulk entry, historical migration, and dashboard refresh.
- A container smoke test migrates a fresh volume and serves the health endpoint and SPA.

## Deployment And Operations

The multi-stage image targets amd64 and arm64. The runtime is non-root, binds
`0.0.0.0:8000`, applies migrations before starting one Uvicorn worker, and uses `/data`
for SQLite, uploads, model artifacts, and backups. The Compose project includes a health
check, restart policy, environment file, and persistent bind mount suitable for Synology.

A Python backup command uses SQLite's online backup API. Synology Task Scheduler runs it
nightly, and Hyper Backup protects the persistent directory. The application is not
intended for direct internet exposure.

The obsolete local PostgreSQL probe is not part of the architecture. Its hardcoded
credentials must not enter source control or the Docker build context. Personal source
files, generated databases, uploads, model artifacts, and backups are excluded from Git
and image builds.

## Delivery Order

1. Foundation and security boundaries.
2. SQLite schema, API contracts, and historical migration.
3. Revolut import and complete review-to-commit vertical slice.
4. DBS, Mastercard, quick entry, and bulk manual entry.
5. Tag rules, reproducible ML training, and versioned inference.
6. Transaction management and reporting pages.
7. Full tests, backups, multi-architecture image, and Synology runbook.

The release is complete only after historical migration and all required input paths pass
end-to-end tests against a fresh persistent volume.
