#!/bin/bash
#
# Build and package shared libraries for inclusion in app builds
#
# This script builds distributable packages from the shared libraries.
# After building, it prints instructions for installing the packages
# in your apps.
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

# Shared library paths
PYTHON_SHARED="$REPO_ROOT/shared/python"
TS_SHARED_DIR="$REPO_ROOT/shared/typescript"

# Track built packages (parallel arrays for bash 3.2 compatibility)
PYTHON_WHEEL=""
TS_PKG_NAMES=()   # Package directory names
TS_PKG_PATHS=()   # Full paths to built .tgz files

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Build shared libraries for app builds."
    echo ""
    echo "Options:"
    echo "  --python-only    Only build Python package"
    echo "  --ts-only        Only build TypeScript package"
    echo "  --clean          Remove existing packages before building"
    echo "  -h, --help       Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0               # Build all packages"
    echo "  $0 --python-only # Build only Python wheel"
    echo "  $0 --clean       # Clean and rebuild all"
    exit 0
}

# Parse arguments
BUILD_PYTHON=true
BUILD_TS=true
CLEAN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --python-only)
            BUILD_TS=false
            shift
            ;;
        --ts-only)
            BUILD_PYTHON=false
            shift
            ;;
        --clean)
            CLEAN=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            ;;
    esac
done

echo -e "${BLUE}=== Building Shared Libraries ===${NC}"
echo ""

# Build Python wheel
build_python() {
    echo -e "${BLUE}Building Python wheel...${NC}"

    if [[ ! -d "$PYTHON_SHARED" ]]; then
        echo -e "${RED}Error: Python shared library not found at $PYTHON_SHARED${NC}"
        return 1
    fi

    # Clean existing dist
    if [[ "$CLEAN" == "true" ]] || [[ -d "$PYTHON_SHARED/dist" ]]; then
        rm -rf "$PYTHON_SHARED/dist"
    fi

    # Build wheel
    cd "$PYTHON_SHARED"
    pip wheel . -w dist/ --no-deps --quiet

    # Find the wheel file
    WHEEL_FILE=$(ls dist/*.whl 2>/dev/null | head -1)
    if [[ -z "$WHEEL_FILE" ]]; then
        echo -e "${RED}Error: No wheel file generated${NC}"
        return 1
    fi

    PYTHON_WHEEL="$PYTHON_SHARED/$WHEEL_FILE"
    WHEEL_NAME=$(basename "$WHEEL_FILE")
    echo -e "  Built: ${GREEN}$WHEEL_NAME${NC}"
    echo ""
}

# Build a single TypeScript package
# Args: $1 = package directory path
build_single_ts_package() {
    local pkg_dir="$1"
    local pkg_name
    pkg_name=$(basename "$pkg_dir")

    echo -e "${BLUE}Building TypeScript package: ${BOLD}$pkg_name${NC}"

    if [[ ! -f "$pkg_dir/package.json" ]]; then
        echo -e "${YELLOW}  Skipping: No package.json found${NC}"
        return 0
    fi

    cd "$pkg_dir"

    # Clean existing tgz files
    if [[ "$CLEAN" == "true" ]]; then
        rm -f ./*.tgz
    fi

    # Install deps if needed
    if [[ ! -d "node_modules" ]]; then
        echo -e "  Installing dependencies..."
        npm install --quiet
    fi

    # Build
    echo -e "  Compiling TypeScript..."
    npm run build --quiet

    # Pack
    echo -e "  Creating package..."
    npm pack --quiet

    # Find the tgz file
    TGZ_FILE=$(ls ./*.tgz 2>/dev/null | head -1)
    if [[ -z "$TGZ_FILE" ]]; then
        echo -e "${RED}Error: No tgz file generated for $pkg_name${NC}"
        return 1
    fi

    # Add to parallel arrays
    TS_PKG_NAMES+=("$pkg_name")
    TS_PKG_PATHS+=("$pkg_dir/$TGZ_FILE")

    TGZ_NAME=$(basename "$TGZ_FILE")
    echo -e "  Built: ${GREEN}$TGZ_NAME${NC}"
    echo ""
}

# Build all TypeScript packages
build_typescript() {
    echo -e "${BLUE}=== Building TypeScript packages ===${NC}"
    echo ""

    if [[ ! -d "$TS_SHARED_DIR" ]]; then
        echo -e "${RED}Error: TypeScript shared directory not found at $TS_SHARED_DIR${NC}"
        return 1
    fi

    # Find all directories with package.json
    local found_packages=0
    for pkg_dir in "$TS_SHARED_DIR"/*/; do
        if [[ -f "${pkg_dir}package.json" ]]; then
            build_single_ts_package "$pkg_dir"
            ((found_packages++)) || true
        fi
    done

    if [[ $found_packages -eq 0 ]]; then
        echo -e "${YELLOW}No TypeScript packages found in $TS_SHARED_DIR${NC}"
    else
        echo -e "${GREEN}Built $found_packages TypeScript package(s)${NC}"
    fi
    echo ""
}

# Print installation instructions
print_instructions() {
    echo -e "${GREEN}=== Build Complete ===${NC}"
    echo ""
    echo -e "${BOLD}${CYAN}Package Locations:${NC}"
    echo ""

    if [[ -n "$PYTHON_WHEEL" ]]; then
        echo -e "  ${BOLD}Python:${NC} $PYTHON_WHEEL"
    fi

    if [[ ${#TS_PKG_NAMES[@]} -gt 0 ]]; then
        echo -e "  ${BOLD}TypeScript:${NC}"
        for i in "${!TS_PKG_NAMES[@]}"; do
            echo -e "    - ${TS_PKG_NAMES[$i]}: ${TS_PKG_PATHS[$i]}"
        done
    fi

    echo ""
    echo -e "${BOLD}${CYAN}Installation Instructions:${NC}"
    echo ""

    if [[ -n "$PYTHON_WHEEL" ]]; then
        WHEEL_NAME=$(basename "$PYTHON_WHEEL")
        echo -e "${BOLD}Python (FastAPI backends):${NC}"
        echo ""
        echo "  1. Copy the wheel to your app's backend directory:"
        echo -e "     ${YELLOW}cp $PYTHON_WHEEL apps/<your-app>/backend/${NC}"
        echo ""
        echo "  2. Add to requirements.txt (at the top, before other deps):"
        echo -e "     ${YELLOW}# Kamiwaza auth shared library (bundled wheel)"
        echo -e "     ./$WHEEL_NAME${NC}"
        echo ""
        echo "  3. In your Dockerfile, the wheel will be installed with:"
        echo -e "     ${YELLOW}pip install -r requirements.txt${NC}"
        echo ""
    fi

    if [[ ${#TS_PKG_NAMES[@]} -gt 0 ]]; then
        echo -e "${BOLD}TypeScript (Next.js frontends):${NC}"
        echo ""
        echo "  For each package you need:"
        echo ""
        for i in "${!TS_PKG_NAMES[@]}"; do
            local pkg_name="${TS_PKG_NAMES[$i]}"
            local pkg_path="${TS_PKG_PATHS[$i]}"
            local tgz_name
            tgz_name=$(basename "$pkg_path")
            # Extract npm package name from package.json
            local pkg_dir
            pkg_dir=$(dirname "$pkg_path")
            local npm_name
            npm_name=$(cd "$pkg_dir" && node -p "require('./package.json').name" 2>/dev/null || echo "@kamiwaza/$pkg_name")

            echo -e "  ${BOLD}$pkg_name:${NC}"
            echo "    1. Copy to frontend:"
            echo -e "       ${YELLOW}cp $pkg_path apps/<your-app>/frontend/${NC}"
            echo ""
            echo "    2. Add to package.json dependencies:"
            echo -e "       ${YELLOW}\"$npm_name\": \"file:./$tgz_name\"${NC}"
            echo ""
        done
        echo "  3. Run npm install to link the packages:"
        echo -e "     ${YELLOW}cd apps/<your-app>/frontend && npm install${NC}"
        echo ""
    fi

    echo -e "${BOLD}${CYAN}Usage Examples:${NC}"
    echo ""

    if [[ -n "$PYTHON_WHEEL" ]]; then
        echo -e "${BOLD}Python imports:${NC}"
        echo -e "  ${YELLOW}from kamiwaza_auth import get_identity, require_auth"
        echo -e "  from kamiwaza_auth.endpoints import create_session_router"
        echo -e "  from kamiwaza_auth.errors import SessionExpiredError${NC}"
        echo ""
    fi

    if [[ ${#TS_PKG_NAMES[@]} -gt 0 ]]; then
        echo -e "${BOLD}TypeScript imports:${NC}"
        # Check if kamiwaza-auth was built
        for i in "${!TS_PKG_NAMES[@]}"; do
            if [[ "${TS_PKG_NAMES[$i]}" == "kamiwaza-auth" ]]; then
                echo -e "  ${YELLOW}// @kamiwaza/auth"
                echo -e "  import { useSession, SessionProvider } from '@kamiwaza/auth'"
                echo -e "  import { createAuthMiddleware } from '@kamiwaza/auth/middleware'${NC}"
                echo ""
            fi
            if [[ "${TS_PKG_NAMES[$i]}" == "kamiwaza-client" ]]; then
                echo -e "  ${YELLOW}// @kamiwaza/client"
                echo -e "  import { KamiwazaClient } from '@kamiwaza/client'"
                echo -e "  import { createServerClient } from '@kamiwaza/client/server'${NC}"
                echo ""
            fi
        done
    fi

    echo -e "${BOLD}Note:${NC} These packages are gitignored. Run this script"
    echo "before building Docker images for apps that use them."
}

# Main
if [[ "$BUILD_PYTHON" == "true" ]]; then
    build_python
fi

if [[ "$BUILD_TS" == "true" ]]; then
    build_typescript
fi

print_instructions
