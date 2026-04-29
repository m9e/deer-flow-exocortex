#!/bin/bash
#
# Discover and list all extensions in the repository
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Default to showing all types
SHOW_TYPE="${1:-all}"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Function to check if extension has required files
check_extension() {
    local ext_path=$1
    local ext_type=$2
    local ext_name=$(basename "$ext_path")

    local has_metadata=false
    local has_dockerfile=false
    local has_compose=false
    local has_readme=false

    [[ -f "$ext_path/kamiwaza.json" ]] && has_metadata=true
    [[ -f "$ext_path/Dockerfile" ]] && has_dockerfile=true
    [[ -f "$ext_path/docker-compose.yml" || -f "$ext_path/docker-compose.appgarden.yml" ]] && has_compose=true
    [[ -f "$ext_path/README.md" ]] && has_readme=true

    # Get version if metadata exists
    local version="unknown"
    if [[ "$has_metadata" == "true" ]]; then
        version=$(python3 -c "import json; print(json.load(open('$ext_path/kamiwaza.json'))['version'])" 2>/dev/null || echo "unknown")
    fi

    # Output extension info
    printf "%-20s %-8s " "$ext_name" "$version"

    # Show status indicators
    [[ "$has_metadata" == "true" ]] && printf "${GREEN}✓${NC}" || printf "${RED}✗${NC}"
    printf " metadata  "
    [[ "$has_dockerfile" == "true" ]] && printf "${GREEN}✓${NC}" || printf "${YELLOW}○${NC}"
    printf " docker  "
    [[ "$has_compose" == "true" ]] && printf "${GREEN}✓${NC}" || printf "${YELLOW}○${NC}"
    printf " compose  "
    [[ "$has_readme" == "true" ]] && printf "${GREEN}✓${NC}" || printf "${YELLOW}○${NC}"
    printf " readme"

    echo
}

# Function to list extensions of a specific type
list_extensions() {
    local ext_type=$1
    local ext_dir="${REPO_ROOT}/${ext_type}s"

    if [[ ! -d "$ext_dir" ]]; then
        echo "No ${ext_type}s directory found"
        return
    fi

    local type_upper=$(echo "${ext_type:0:1}" | tr '[:lower:]' '[:upper:]')${ext_type:1}
    echo -e "\n${BLUE}=== ${type_upper}s ===${NC}"
    echo "Name                 Version  Metadata Docker Compose README"
    echo "-------------------- -------- -------- ------ ------- ------"

    for ext_path in "$ext_dir"/*; do
        if [[ -d "$ext_path" ]] && [[ ! "$(basename "$ext_path")" =~ ^\. ]]; then
            check_extension "$ext_path" "$ext_type"
        fi
    done
}

# Main logic
echo "Kamiwaza Extensions Discovery"
echo "============================"

case "$SHOW_TYPE" in
    app|apps)
        list_extensions "app"
        ;;
    service|services)
        list_extensions "service"
        ;;
    tool|tools)
        list_extensions "tool"
        ;;
    all|*)
        list_extensions "app"
        list_extensions "service"
        list_extensions "tool"
        ;;
esac

echo -e "\n${YELLOW}Legend:${NC} ${GREEN}✓${NC} present, ${RED}✗${NC} missing, ${YELLOW}○${NC} optional"
