# Tagging Model Training

After imports have committed enough labeled transactions, train and activate the production
model in a one-off container. Pass all host-selection arguments explicitly:

```sh
docker compose \
  --env-file "$HOME/.config/personal-finance-ledger/main.env" \
  --project-name finance-main \
  --project-directory "$PWD" \
  -f "$PWD/compose.yaml" \
  run --rm --no-deps \
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
