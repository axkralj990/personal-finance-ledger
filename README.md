# Personal Finance Ledger

A private, self-hosted ledger for importing, reviewing, and reporting personal transactions
and manually managed assets. The production app is a React single-page application served
by a FastAPI API, with a local SQLite database and retained import files under one
persistent data directory.

## Architecture

- `frontend/`: React, TypeScript, and Vite SPA
- `backend/`: FastAPI API, SQLAlchemy, Alembic migrations, and import CLI
- `/data`: production SQLite database, retained uploads, backups, and model artifacts
- Legacy Dash code remains in the repository for historical reference and is not included in the production image.

The app has no authentication. Treat all transaction data as sensitive and expose the service only to a trusted LAN or VPN.

## Local Development

Install Python dependencies and start the API:

```sh
uv sync
uv run uvicorn backend.app.asgi:app --reload --host 127.0.0.1 --port 8000
```

In another terminal, install frontend dependencies and start Vite:

```sh
cd frontend
npm ci
npm run dev
```

Vite proxies `/api` and `/health` to the backend on port 8000.

## Tests

```sh
uv run pytest backend/tests
cd frontend && npm test
```

## Automatic Tagging

After committed transactions contain reviewed category labels, train the local automatic
tagger with:

```sh
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

## Portfolio Quotes

The Portfolio page supports manual dated valuations in EUR, USD, GBP, and CHF. Non-EUR
values use signed ECB reference-rate previews. Twelve Data is the preferred quote provider;
set its API key in `.env`:

```dotenv
TWELVE_DATA_API_KEY=your-personal-key
```

The key remains server-side. When Twelve Data cannot access an LSE instrument, the server
falls back to Yahoo Finance and records explicit `YAHOO_FINANCE` provenance. Yahoo Finance
is an unofficial, keyless source and may change without notice. Quotes are reviewed before
saving, and failed refreshes retain the previous valuation. Manual portfolio management
works when both providers are unavailable.

For supported LSE holdings, **Update history** backfills missing completed months from Yahoo
Finance and converts each month-end close with the corresponding ECB reference rate. The
Portfolio graph can switch between aggregate history and an individual asset's market value,
cost basis, and unrealized P&L. Re-running history updates only missing months.

## Production Quick Start

```sh
cp .env.example .env
# Edit FINANCE_DATA_PATH and FINANCE_HOST_PORT in .env.
docker compose build
docker compose up -d
docker compose ps
```

On Linux and Synology, create `FINANCE_DATA_PATH` first and grant UID/GID `10001:10001` access. The service is available at `http://<host>:<FINANCE_HOST_PORT>`.

See the [Synology deployment runbook](docs/deployment/synology.md), [historical data migration](docs/deployment/migration.md), and [backup and restore guide](docs/deployment/backup-restore.md).

## Privacy

Repository `data/`, SQLite files, uploads, backups, model artifacts, `.env`, and `test_db.py` are excluded from Git and the Docker build context. Do not add personal CSV files or credentials to the image, Git history, logs, or issue reports.
