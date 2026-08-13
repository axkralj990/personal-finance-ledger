# Personal Finance Ledger

A private, self-hosted ledger for importing, reviewing, and reporting personal transactions
and manually managed assets. The production app is a React single-page application served
by a FastAPI API, with a local SQLite database and retained import files under one
persistent data directory.

## Architecture

- `frontend/`: React, TypeScript, and Vite SPA
- `backend/`: FastAPI API, SQLAlchemy, Alembic migrations, and import CLI
- `/data`: production SQLite database, retained uploads, backups, and model artifacts
- The pre-FastAPI Dash prototype is preserved on the `legacy` branch.

The app has no authentication. Treat all transaction data as sensitive and expose the service only to a trusted LAN or VPN.

## Local Development

Install Python dependencies and start the API:

```sh
uv sync
mkdir -p "$HOME/.local/share/personal-finance-ledger/test"
DATA_DIR="$HOME/.local/share/personal-finance-ledger/test" \
  uv run uvicorn backend.app.asgi:app --reload --host 127.0.0.1 --port 18000
```

In another terminal, install frontend dependencies and start Vite:

```sh
cd frontend
npm ci
npm run dev
```

Vite proxies `/api` and `/health` to the isolated test backend on port `18000` by default.
Set `VITE_API_PROXY_TARGET` to use another target. Do not point routine frontend development
at production.

## Tests

```sh
uv run pytest backend/tests
cd frontend && npm test
```

## Automatic Tagging

After committed transactions contain reviewed category labels, train the local automatic
tagger with:

```sh
DATA_DIR="$HOME/.local/share/personal-finance-ledger/test" \
  uv run python -m backend.app.cli train-model
```

The default minimum confidence is `0.70` for categories and `0.80` for subcategories.
Use `--category-threshold` and `--subcategory-threshold` to override them. Training writes
a new version under `DATA_DIR/models`, atomically activates its database metadata, and
retains prior artifacts as inactive versions. Imports continue as manual review when no
valid model is active or a prediction is below its required threshold.

Model files use joblib's pickle-based format. Load only artifacts created locally by this
application or restored from a trusted backup. Never place artifacts from untrusted sources
in the models directory.

## Optional OpenAI Mapping

OpenAI-assisted mapping is disabled by default. To enable the server-side boundary, set
`OPENAI_MAPPING_ENABLED=true` and `OPENAI_API_KEY` in the external environment file; keep the key out of the browser,
logs, screenshots, and source control. Only headers, local type information, and at most 12
deterministically selected rows of allowlisted or tokenized values are sent. Imports always
retain a manual mapping fallback. Configure the provider account for the lowest available
retention and data-use setting before enabling it. Also set `ALLOWED_HOSTS` to the exact LAN or
reverse-proxy hostnames and `ALLOWED_ORIGINS` to the full browser origins used to open the app.

## Portfolio Quotes

The Portfolio page supports manual dated valuations in EUR, USD, GBP, and CHF. Non-EUR
values use signed ECB reference-rate previews. Market quotes come from Yahoo Finance and
record explicit `YAHOO_FINANCE` provenance. Yahoo Finance is an unofficial, keyless source
and may change without notice. Quotes are reviewed before saving, and failed refreshes
retain the previous valuation. Manual portfolio management works when Yahoo is unavailable.

For supported London, Amsterdam, and Xetra holdings, **Update history** backfills missing
completed months from Yahoo Finance and converts each month-end close with the corresponding
ECB reference rate. Re-running history updates only missing months.

## Environments

```sh
mkdir -p "$HOME/.config/personal-finance-ledger"
cp environments/main.env.example "$HOME/.config/personal-finance-ledger/main.env"
cp environments/test.env.example "$HOME/.config/personal-finance-ledger/test.env"
```

The current branch selects the environment:

```sh
git switch main
./scripts/finance.sh start   # production, port 8000

git switch test
./scripts/finance.sh start   # synthetic test data, port 18000
./scripts/finance.sh reset   # restore deterministic test data
```

`FINANCE_DATA_PATH` is required and points outside the repository. `backup` is available only
on `main`; `reset` is available only on `test`.

See the [Synology deployment runbook](docs/deployment/synology.md), [tagging model training](docs/deployment/migration.md),
and the [backup and restore guide](docs/deployment/backup-restore.md).

## Privacy

Repository `data/`, SQLite files, uploads, backups, model artifacts, local environment files,
and `test_db.py` are excluded from Git and the Docker build context. Host configuration belongs
under `$HOME/.config/personal-finance-ledger` by default. Do not add personal CSV files or
credentials to the image, Git history, logs, or issue reports.
