#!/bin/sh
set -eu

usage() {
  echo "Usage: $0 <start|stop|status|logs|reset|backup>" >&2
  exit 2
}

[ "$#" -eq 1 ] || usage
command=$1
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
branch=$(git -C "$project_dir" branch --show-current)

case "$branch" in
  main) environment=main ;;
  test) environment=test ;;
  *)
    echo "Run this command from the main or test branch, not $branch" >&2
    exit 1
    ;;
esac

env_dir=${FINANCE_ENV_DIR:-"$HOME/.config/personal-finance-ledger"}
env_file="$env_dir/$environment.env"
[ -f "$env_file" ] || {
  echo "Environment file not found: $env_file" >&2
  exit 1
}

compose() {
  docker compose --env-file "$env_file" --project-name "finance-$environment" \
    --project-directory "$project_dir" -f "$project_dir/compose.yaml" "$@"
}

case "$command" in
  start) compose up --detach --build ;;
  stop) compose down ;;
  status) compose ps ;;
  logs) compose logs --follow --tail=100 app ;;
  reset)
    [ "$branch" = test ] || { echo "reset is only available on test" >&2; exit 1; }
    compose stop app
    compose run --rm --no-deps app python -m backend.app.cli seed-test-data --reset
    compose up --detach app
    ;;
  backup)
    [ "$branch" = main ] || { echo "backup is only available on main" >&2; exit 1; }
    "$project_dir/scripts/backup.sh" "$env_file" "finance-main"
    ;;
  *) usage ;;
esac
