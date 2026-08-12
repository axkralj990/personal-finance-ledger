# Historical Data Migration

The historical CSV remains on the host and is excluded from both Git and the Docker build context. Run migration only after the production service has initialized its persistent `/data` directory.

From the repository root, temporarily mount the containing directory read-only and run the migration CLI in a one-off container:

```sh
docker compose run --rm --no-deps \
  -v "$(pwd)/data/dashboard:/migration:ro" \
  app python -m backend.app.cli migrate-history \
  --file /migration/transactions.csv --commit-clean
```

Compose also mounts the configured `FINANCE_DATA_PATH` at `/data` in this one-off container. The CLI copies the source into `/data/uploads` for audit/review, stages all rows, and commits only clean rows. The original CSV is never copied into the image.

For the current historical file, the verified aggregate result is 2,787 staged, 2,748 committed, 22 exact blocked, 16 likely review, and one parse error pending. Verify it without printing transaction contents:

```text
staged=2787
committed=2748
exact_blocked=22
likely_review=16
parse_errors=1
```

The remaining 39 rows consist of 22 exact duplicates, 16 likely duplicates, and one parse error. Resolve them in the application's **Import review** screen. Exact duplicates remain blocked unless deliberately resolved; likely duplicates and the parse error require review.

Migration is idempotent. The CLI identifies the retained import batch by source account and SHA-256 file digest. Rerunning the same command reuses that batch and does not duplicate committed transactions.

## Train the First Tagging Model

After the historical migration has committed its clean labeled transactions, train and
activate the first model in a one-off container:

```sh
docker compose run --rm --no-deps \
  app python -m backend.app.cli train-model
```

The command reads committed, non-excluded labeled transactions from SQLite and writes a
versioned artifact below `/data/models`. It prints aggregate training rows, category count,
subcategory model/constant counts, and library/taxonomy versions only. It does not print
transaction descriptions. The default confidence thresholds are `0.70` for category and
`0.80` for subcategory predictions.

After reviewing imports or correcting committed labels, rerun the same command. Every run
creates a new version and atomically deactivates the prior database record. Existing artifact
files remain available for backup and audit. Optional stricter thresholds can be supplied as
`--category-threshold 0.75 --subcategory-threshold 0.85`.

Artifacts use joblib's pickle-based format and must be treated as executable trusted-local
data. Restore them only from a trusted backup; never import model files from an untrusted
source.
