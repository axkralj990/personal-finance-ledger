# Main and Pull Request CI Design

## Goal

Run the repository's complete quality checks after every push to `main` and for every pull request
targeting `main`.

## Workflow

Keep one `.github/workflows/ci.yml` workflow with these triggers:

- `push` events whose branch is `main`.
- `pull_request` events whose target branch is `main`.

Do not run the workflow for routine pushes to feature or test branches. Keep the current workflow
permissions and per-ref concurrency behavior, including cancellation of stale runs for the same
ref.

## Checks

Preserve the existing independent jobs:

- Backend: frozen development dependency sync, Ruff lint, and backend pytest suite.
- Frontend: clean npm install, Vitest suite, TypeScript checking, ESLint, and production build.

The same jobs run for both event types so pull-request validation and post-merge `main` validation
cannot drift.

## Verification

Validate the workflow syntax and inspect the resulting trigger structure. Run the backend and
frontend quality commands documented in the README. Confirm no application or deployment behavior
changes are included.
