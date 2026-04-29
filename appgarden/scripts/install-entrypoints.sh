#!/bin/bash
#
# Install shared entrypoint scripts into extension directories
#
# Copies shared Docker entrypoint scripts to target extension directories
# for inclusion in Docker builds.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Available entrypoint scripts
ENTRYPOINTS_DIR="$REPO_ROOT/scripts"
AVAILABLE_ENTRYPOINTS="kamiwaza-entrypoint.sh"

usage() {
    echo "Usage: $0 <type> <name> [options]"
    echo ""
    echo "Install shared entrypoint scripts into an extension."
    echo ""
    echo "Required:"
    echo "  <type>              Extension type: app, service, or tool"
    echo "  <name>              Extension name"
    echo ""
    echo "Options:"
    echo "  --scripts=LIST      Comma-separated list of scripts to install"
    echo "                      Default: all available (kamiwaza-entrypoint.sh)"
    echo "  --path=PATH         Override install path (relative to extension root)"
    echo "                      Default: scripts/"
    echo "  -h, --help          Show this help message"
    echo ""
    echo "Available entrypoint scripts:"
    echo "  kamiwaza-entrypoint.sh - SSL certificate trust for Kamiwaza internal services"
    echo ""
    echo "Examples:"
    echo "  $0 app my-app                              # Install all to apps/my-app/scripts/"
    echo "  $0 service my-svc                          # Install all to services/my-svc/scripts/"
    echo "  $0 tool my-tool                            # Install all to tools/my-tool/scripts/"
    echo "  $0 app my-app --scripts=kamiwaza-entrypoint.sh"
    echo "  $0 app my-app --path=docker/scripts/"
    exit 0
}

# Parse arguments
TYPE=""
NAME=""
SCRIPTS="$AVAILABLE_ENTRYPOINTS"
INSTALL_PATH="scripts"

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            ;;
        --scripts=*)
            SCRIPTS="${1#*=}"
            shift
            ;;
        --path=*)
            INSTALL_PATH="${1#*=}"
            shift
            ;;
        *)
            if [ -z "$TYPE" ]; then
                TYPE="$1"
            elif [ -z "$NAME" ]; then
                NAME="$1"
            else
                echo -e "${RED}Error: Unexpected argument: $1${NC}"
                exit 1
            fi
            shift
            ;;
    esac
done

# Validate required args
if [ -z "$TYPE" ] || [ -z "$NAME" ]; then
    echo -e "${RED}Error: TYPE and NAME are required${NC}"
    echo "Usage: $0 <type> <name> [options]"
    exit 1
fi

# Validate type
if [ "$TYPE" != "app" ] && [ "$TYPE" != "service" ] && [ "$TYPE" != "tool" ]; then
    echo -e "${RED}Error: TYPE must be 'app', 'service', or 'tool'${NC}"
    exit 1
fi

# Determine extension path
case "$TYPE" in
    app)
        EXT_DIR="$REPO_ROOT/apps/$NAME"
        ;;
    service)
        EXT_DIR="$REPO_ROOT/services/$NAME"
        ;;
    tool)
        EXT_DIR="$REPO_ROOT/tools/$NAME"
        ;;
esac

# Check extension exists
if [ ! -d "$EXT_DIR" ]; then
    echo -e "${RED}Error: Extension not found: $EXT_DIR${NC}"
    exit 1
fi

# Target directory
TARGET_DIR="$EXT_DIR/$INSTALL_PATH"

echo -e "${BLUE}${BOLD}Installing entrypoint scripts${NC}"
echo -e "  Extension: ${CYAN}${TYPE}s/$NAME${NC}"
echo -e "  Target:    ${CYAN}$INSTALL_PATH${NC}"
echo ""

# Create target directory if needed
mkdir -p "$TARGET_DIR"

# Install each requested script
IFS=',' read -ra SCRIPT_LIST <<< "$SCRIPTS"
INSTALLED=0

for script in "${SCRIPT_LIST[@]}"; do
    script=$(echo "$script" | xargs)  # trim whitespace
    SOURCE="$ENTRYPOINTS_DIR/$script"

    if [ ! -f "$SOURCE" ]; then
        echo -e "${YELLOW}Warning: Script not found: $script${NC}"
        continue
    fi

    cp "$SOURCE" "$TARGET_DIR/"
    chmod +x "$TARGET_DIR/$script"
    echo -e "  ${GREEN}✓${NC} Installed: $script"
    ((INSTALLED++))
done

echo ""
if [ $INSTALLED -gt 0 ]; then
    echo -e "${GREEN}${BOLD}Successfully installed $INSTALLED entrypoint script(s)${NC}"
    echo ""
    echo -e "Usage in Dockerfile:"
    echo -e "  ${CYAN}COPY $INSTALL_PATH/kamiwaza-entrypoint.sh /kamiwaza-entrypoint.sh${NC}"
    echo -e "  ${CYAN}RUN chmod +x /kamiwaza-entrypoint.sh${NC}"
    echo -e "  ${CYAN}ENTRYPOINT [\"/kamiwaza-entrypoint.sh\"]${NC}"
    echo -e "  ${CYAN}CMD [\"your-command\"]${NC}"
else
    echo -e "${YELLOW}No scripts were installed${NC}"
    exit 1
fi
