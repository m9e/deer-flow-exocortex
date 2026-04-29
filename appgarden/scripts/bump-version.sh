#!/bin/bash
#
# Bump the version in an extension's kamiwaza.json
# Usage: ./scripts/bump-version.sh <type> <name> <PATCH|MINOR|MAJOR>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

usage() {
  echo "Usage: $0 <type> <name> <PATCH|MINOR|MAJOR>"
  echo "Example: $0 app coe-app PATCH"
  exit 1
}

TYPE="${1:-}"
NAME="${2:-}"
LEVEL="${3:-}"

if [[ -z "$TYPE" || -z "$NAME" || -z "$LEVEL" ]]; then
  usage
fi

LEVEL_UPPER=$(echo "$LEVEL" | tr '[:lower:]' '[:upper:]')
if [[ "$LEVEL_UPPER" != "PATCH" && "$LEVEL_UPPER" != "MINOR" && "$LEVEL_UPPER" != "MAJOR" ]]; then
  usage
fi

EXT_PATH="${REPO_ROOT}/${TYPE}s/${NAME}"
JSON_PATH="${EXT_PATH}/kamiwaza.json"

if [[ ! -f "$JSON_PATH" ]]; then
  echo "Error: $JSON_PATH not found" >&2
  exit 1
fi

python3 - "$JSON_PATH" "$LEVEL_UPPER" <<'PY'
import json, sys
from pathlib import Path

json_path = Path(sys.argv[1])
level = sys.argv[2]

data = json.loads(json_path.read_text())
old_ver = data.get("version")
if not old_ver:
    print(f"Error: version missing in {json_path}", file=sys.stderr)
    sys.exit(1)

parts = old_ver.split(".")
if len(parts) != 3 or not all(p.isdigit() for p in parts):
    print(f"Error: version '{old_ver}' is not in MAJOR.MINOR.PATCH", file=sys.stderr)
    sys.exit(1)

major, minor, patch = map(int, parts)
if level == "PATCH":
    patch += 1
elif level == "MINOR":
    minor += 1
    patch = 0
elif level == "MAJOR":
    major += 1
    minor = 0
    patch = 0

new_ver = f"{major}.{minor}.{patch}"
data["version"] = new_ver
json_path.write_text(json.dumps(data, indent=2) + "\n")
print(f"{old_ver} -> {new_ver}")
PY
