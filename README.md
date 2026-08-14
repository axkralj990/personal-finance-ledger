# Personal Finance Ledger

[![CI](https://github.com/axkralj990/LifeDashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/axkralj990/LifeDashboard/actions/workflows/ci.yml)
[![Latest version](https://img.shields.io/github/v/tag/axkralj990/LifeDashboard?sort=semver)](https://github.com/axkralj990/LifeDashboard/tags)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Node.js 24](https://img.shields.io/badge/Node.js-24-5FA04E?logo=nodedotjs&logoColor=white)](frontend/package.json)

A private, self-hosted ledger for importing, reviewing, and reporting personal transactions
and manually managed assets. Its local ML categorizer learns from reviewed transaction labels
and suggests categories and subcategories for new imports when predictions meet the configured
confidence thresholds. Imports fall back to manual review when no model is active or confidence
is too low.

The production app is a React single-page application served by a FastAPI API, with a local
SQLite database and retained import files under one persistent data directory.

The app has no authentication. Treat all transaction data as sensitive and expose the service
only to a trusted LAN or VPN.

## Architecture

- `frontend/`: React, TypeScript, and Vite SPA
- `backend/`: FastAPI API, SQLAlchemy, Alembic migrations, and import CLI
- `/data`: production SQLite database, retained uploads, backups, and model artifacts
- The pre-FastAPI Dash prototype is preserved on the `legacy` branch.

## Production and Test Environments

The containerized environments require Git, Docker, and Docker Compose. Create separate external
configuration and data directories once:

```sh
mkdir -p "$HOME/.config/personal-finance-ledger"
mkdir -p "$HOME/.local/share/personal-finance-ledger/production"
mkdir -p "$HOME/.local/share/personal-finance-ledger/test"
test -f "$HOME/.config/personal-finance-ledger/main.env" || \
  cp environments/main.env.example "$HOME/.config/personal-finance-ledger/main.env"
test -f "$HOME/.config/personal-finance-ledger/test.env" || \
  cp environments/test.env.example "$HOME/.config/personal-finance-ledger/test.env"
```

Do not overwrite environment files that already contain local settings. Review both files before
starting the app. `FINANCE_DATA_PATH` is required, must resolve to an absolute path outside the
repository, and must differ between production and test. Set `ALLOWED_HOSTS` and
`ALLOWED_ORIGINS` to the exact hosts and browser origins used to access each environment.

The checked-out branch selects the environment. `scripts/finance.sh` intentionally rejects all
branches except `main` and `test`.

### Production

Production runs from `main` on port `8000` by default and uses the production data directory:

```sh
git switch main
git pull --ff-only origin main
./scripts/finance.sh start
./scripts/finance.sh status
```

Open `http://127.0.0.1:8000`. Operational commands are:

```sh
./scripts/finance.sh logs
./scripts/finance.sh backup
./scripts/finance.sh stop
```

`backup` is available only on `main`. Back up production before deployments, upgrades, and
database migrations.

### Test

Test runs from `test` on port `18000` by default and uses isolated synthetic data:

```sh
git switch test
git pull --ff-only origin test
./scripts/finance.sh start
./scripts/finance.sh reset
./scripts/finance.sh status
```

Open `http://127.0.0.1:18000`. `reset` is available only on `test` and replaces the test database
with deterministic seed data. Use `./scripts/finance.sh logs` to inspect the service and
`./scripts/finance.sh stop` when finished. Never point the test environment at the production data
directory.

For either running environment, verify the health endpoint using its configured port:

```sh
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:18000/health
```

See the [Synology deployment runbook](docs/deployment/synology.md),
[production model training guide](docs/deployment/migration.md), and
[backup and restore guide](docs/deployment/backup-restore.md) for production operations.

## Local Development

Local development requires Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 24, and npm.
Create a typed development branch from an up-to-date `main` before changing code.

Install Python dependencies and start the API against isolated test data:

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

Vite proxies `/api` and `/health` to the isolated backend on port `18000` by default. Set
`VITE_API_PROXY_TARGET` to use another target. Do not point routine development at production.

### Quality Checks

Run the same checks required by CI before promoting a change:

```sh
uv run ruff check backend
uv run pytest backend/tests

cd frontend
npm test
npm run typecheck
npm run lint
npm run build
```

## Development Workflow

All work follows the `feature branch -> test -> main` promotion path.

1. Update `main` and create a typed, kebab-case branch:

   ```sh
   git switch main
   git pull --ff-only origin main
   git switch -c feature/import-rules
   ```

2. Develop against isolated test data, run all quality checks, commit focused changes, and push
   the branch:

   ```sh
   git push --set-upstream origin feature/import-rules
   ```

3. Merge the feature branch into `test`, push `test`, and validate the complete containerized
   application with synthetic data:

   ```sh
   git switch test
   git pull --ff-only origin test
   git merge --no-ff feature/import-rules
   git push origin test
   ./scripts/finance.sh start
   ./scripts/finance.sh reset
   ./scripts/finance.sh status
   ```

4. After test validation succeeds, open a pull request from the same feature branch into `main`.
   Merge only after review and all CI checks pass. Do not merge `test` into `main` as a substitute
   for the focused feature pull request.

5. Delete the feature branch after it reaches `main`. Keep `main` deployable and use `test` only
   for pre-production validation with non-production data.

## Development Standards

- Use `feature/`, `fix/`, `docs/`, `refactor/`, or `chore/` followed by a short kebab-case name.
- Use Conventional Commit subjects such as `feat: add import rules`, `fix: handle empty files`, or
  `docs: document releases`.
- Keep branches, commits, and pull requests focused on one coherent change.
- Add or update tests when behavior changes. Every pull request into `main` must pass backend lint
  and tests plus frontend tests, type checking, lint, and build.
- Add an Alembic migration for every database schema change. Do not edit an applied migration.
- Never commit credentials, personal finance data, SQLite files, uploads, backups, model artifacts,
  or local environment files.
- Document operational, configuration, migration, or compatibility changes in the same pull
  request as the code that introduces them.

## Releases

Releases use [Semantic Versioning](https://semver.org/) and annotated Git tags named
`vMAJOR.MINOR.PATCH`:

- Increment `PATCH` for backward-compatible fixes, for example `v1.2.3` to `v1.2.4`.
- Increment `MINOR` for backward-compatible functionality, for example `v1.2.3` to `v1.3.0`.
- Increment `MAJOR` for incompatible changes, for example `v1.2.3` to `v2.0.0`.

Before tagging, merge a normal pull request that sets the same version in `pyproject.toml`,
`frontend/package.json`, and `frontend/package-lock.json`. Confirm CI passes and the production
database has a current backup. Then create the tag from an up-to-date, clean `main` branch:

```sh
git switch main
git pull --ff-only origin main
git status --short
git tag -a v1.2.0 -m "Release v1.2.0"
git push origin v1.2.0
git show --stat v1.2.0
```

`git status --short` must produce no output before tagging. Create release tags only from `main`,
never from `test` or a development branch. GitHub release notes may be added after pushing the tag.

## Automatic Categorization

After committed transactions contain reviewed category labels, train the local automatic
categorizer with:

```sh
DATA_DIR="$HOME/.local/share/personal-finance-ledger/test" \
  uv run python -m backend.app.cli train-model
```

The default minimum confidence is `0.70` for categories and `0.80` for subcategories. Use
`--category-threshold` and `--subcategory-threshold` to override them. Training writes a new
version under `DATA_DIR/models`, atomically activates its database metadata, and retains prior
artifacts as inactive versions. Imports continue as manual review when no valid model is active or
a prediction is below its required threshold.

Model files use joblib's pickle-based format. Load only artifacts created locally by this
application or restored from a trusted backup. Never place artifacts from untrusted sources in the
models directory.

## Optional OpenAI Mapping

OpenAI-assisted mapping is disabled by default. To enable the server-side boundary, set
`OPENAI_MAPPING_ENABLED=true` and `OPENAI_API_KEY` in the external environment file; keep the key
out of the browser, logs, screenshots, and source control. Only headers, local type information,
and at most 12 deterministically selected rows of allowlisted or tokenized values are sent. Imports
always retain a manual mapping fallback. Configure the provider account for the lowest available
retention and data-use setting before enabling it. Also set `ALLOWED_HOSTS` to the exact LAN or
reverse-proxy hostnames and `ALLOWED_ORIGINS` to the full browser origins used to open the app.

## Portfolio Quotes

The Portfolio page supports manual dated valuations in EUR, USD, GBP, and CHF. Non-EUR values use
signed ECB reference-rate previews. Market quotes come from Yahoo Finance and record explicit
`YAHOO_FINANCE` provenance. Yahoo Finance is an unofficial, keyless source and may change without
notice. Quotes are reviewed before saving, and failed refreshes retain the previous valuation.
Manual portfolio management works when Yahoo is unavailable.

For supported London, Amsterdam, and Xetra holdings, **Update history** backfills missing completed
months from Yahoo Finance and converts each month-end close with the corresponding ECB reference
rate. Re-running history updates only missing months.

## Privacy

Repository `data/`, SQLite files, uploads, backups, model artifacts, local environment files, and
`test_db.py` are excluded from Git and the Docker build context. Host configuration belongs under
`$HOME/.config/personal-finance-ledger` by default. Do not add personal CSV files or credentials to
the image, Git history, logs, or issue reports.
