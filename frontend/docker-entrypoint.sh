#!/bin/sh
set -e

BUILD_MAX_OLD_SPACE_SIZE="${NEXT_BUILD_MAX_OLD_SPACE_SIZE:-1536}"
APP_DIR="/app/frontend"
RUNTIME_ROOT="/tmp/deer-flow-frontend"
RUNTIME_DIR="${RUNTIME_ROOT}/runtime"

export NEXT_TELEMETRY_DISABLED=1
export NODE_OPTIONS="--max-old-space-size=${BUILD_MAX_OLD_SPACE_SIZE} ${NODE_OPTIONS:-}"

normalize_path() {
  echo "$1" | sed 's:/*$::'
}

CURRENT_BASE_PATH=""
if [ -n "${KAMIWAZA_APP_PATH:-}" ]; then
  CURRENT_BASE_PATH=$(normalize_path "$KAMIWAZA_APP_PATH")
fi

if [ -n "$CURRENT_BASE_PATH" ]; then
  export NEXT_PUBLIC_APP_BASE_PATH="$CURRENT_BASE_PATH"
  echo "Path-based routing: ${NEXT_PUBLIC_APP_BASE_PATH}"
  echo "Rebuilding Next.js for App Garden basePath..."
  rm -rf "$RUNTIME_ROOT"
  mkdir -p "$RUNTIME_DIR"
  cp -R "$APP_DIR/." "$RUNTIME_DIR/"
  cd "$RUNTIME_DIR"
  SKIP_ENV_VALIDATION=1 pnpm build
else
  echo "Port-based routing mode"
  cd "$APP_DIR"
fi

exec "$@"
