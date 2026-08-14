# README Development and Release Guide Design

## Goal

Make the README the authoritative entry point for running production and test environments,
developing changes safely, and publishing SemVer releases.

## README Structure

Add CI, latest tagged version, Python 3.12, and Node 24 badges immediately below the title. Expand
the opening description with a short explanation of the local automatic categorization model:
reviewed labels train the model, confident predictions suggest categories and subcategories during
import, and unavailable or low-confidence predictions return to manual review.

Move environment setup ahead of feature-specific documentation. Cover shared configuration and
then distinguish:

- Production on `main`, port `8000`, with real data and backup support.
- Test on `test`, port `18000`, with isolated synthetic data and deterministic reset support.
- Local development on typed branches, using the test data directory and Vite proxy.

Include status, logs, health-check, stop, reset, and backup commands where each command is valid.
Retain the warning that the unauthenticated application must remain on a trusted LAN or VPN.

## Development Workflow

Document this promotion path:

1. Update local `main` from `origin/main`.
2. Create a typed, kebab-case branch from `main`, such as `feature/import-rules`.
3. Develop locally against isolated test data.
4. Run backend lint/tests and frontend tests/type checking/lint/build.
5. Merge the feature branch into `test` and validate the containerized test environment.
6. Open the same feature branch into `main`; merge only after CI and review succeed.

Accepted branch prefixes are `feature/`, `fix/`, `docs/`, `refactor/`, and `chore/`. Commits follow
the repository's Conventional Commit style. Changes must not include credentials, personal finance
data, databases, uploads, model artifacts, or external environment files. Database schema changes
must include migrations, and changed behavior must have appropriate tests.

## Releases

Use Semantic Versioning and annotated tags in the form `vMAJOR.MINOR.PATCH`:

- Increment `PATCH` for backward-compatible fixes.
- Increment `MINOR` for backward-compatible functionality.
- Increment `MAJOR` for incompatible changes.

Create release tags only from an up-to-date `main` after validation. Document commands to switch
and pull `main`, create an annotated tag, push the tag, and verify it. Do not release from `test` or
a feature branch. GitHub release notes remain optional.

## Existing Documentation

Preserve the architecture, automatic tagging details, OpenAI mapping, portfolio quotes, privacy,
and deployment-runbook links. Consolidate duplicated setup content rather than maintaining two
competing environment guides.

## Verification

Check every documented command against `scripts/finance.sh`, `.github/workflows/ci.yml`,
`pyproject.toml`, and `frontend/package.json`. Review links, badge URLs, branch names, ports, and
SemVer examples for consistency. No application behavior changes are required.
