#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${1:-ai-chatbot-app}"
TEMPLATE_ID="${TEMPLATE_ID:-}"

step() {
  printf "\n\033[1;35m== %s ==\033[0m\n" "$1"
}

if [[ ! -d "apps/${APP_NAME}" ]]; then
  echo "App '${APP_NAME}' not found under apps/." >&2
  exit 1
fi

step "Cleaning build artifacts"
rm -rf build

step "Building app (${APP_NAME})"
make build TYPE=app NAME="${APP_NAME}"

if [[ "${DEMO_SKIP_TESTS:-1}" == "1" ]]; then
  step "Skipping unit tests (set DEMO_SKIP_TESTS=0 to run)"
else
  step "Running unit tests"
  make test TYPE=app NAME="${APP_NAME}"
fi

step "Syncing App Garden compose"
make sync-compose TYPE=app NAME="${APP_NAME}"

step "Validating metadata and compose"
make validate TYPE=app NAME="${APP_NAME}"

step "Building registry artifacts"
make build-registry

step "Listing remote templates (before push)"
make garden-list || true

step "Pushing updated template to Kamiwaza"
if [[ -n "${TEMPLATE_ID}" ]]; then
  make garden-push TYPE=app NAME="${APP_NAME}" TEMPLATE_ID="${TEMPLATE_ID}"
else
  make garden-push TYPE=app NAME="${APP_NAME}"
fi

step "Listing remote templates (after push)"
make garden-list
