#!/bin/bash
#
# Install shared library packages into extension directories
#
# Copies pre-built Python wheel and/or TypeScript packages to target
# extension directories for inclusion in Docker builds.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors (matching existing conventions from package-shared-libs.sh)
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Shared library source paths
PYTHON_DIST="$REPO_ROOT/shared/python/dist"
TS_SHARED_DIR="$REPO_ROOT/shared/typescript"

# Known TypeScript packages (parallel arrays for bash 3.2 compatibility)
TS_SHORT_NAMES=("auth" "client")
TS_DIR_NAMES=("kamiwaza-auth" "kamiwaza-client")

# Map short name to directory name (bash 3.2 compatible)
map_short_to_dir() {
    local short_name="$1"
    case "$short_name" in
        auth)   echo "kamiwaza-auth" ;;
        client) echo "kamiwaza-client" ;;
        *)      echo "" ;;
    esac
}

# Get all short names as space-separated string
get_all_short_names() {
    echo "${TS_SHORT_NAMES[*]}"
}

usage() {
    echo "Usage: $0 <type> <name> [options]"
    echo ""
    echo "Install shared library packages into an extension."
    echo ""
    echo "Required:"
    echo "  <type>              Extension type: app, service, or tool"
    echo "  <name>              Extension name"
    echo ""
    echo "Options:"
    echo "  --python-only       Only install Python wheel"
    echo "  --ts-only           Only install TypeScript packages"
    echo "  --libs=LIST         Comma-separated list of packages (auth,client)"
    echo "                      Default: all available packages"
    echo "  --py-path=PATH      Override Python install path"
    echo "  --ts-path=PATH      Override TypeScript install path"
    echo "  -h, --help          Show this help message"
    echo ""
    echo "Default paths:"
    echo "  Apps:   Python -> apps/{name}/backend/"
    echo "          TypeScript -> apps/{name}/frontend/"
    echo "  Services: Python -> services/{name}/"
    echo "            TypeScript -> services/{name}/"
    echo "  Tools:    Python -> tools/{name}/"
    echo "            TypeScript -> tools/{name}/"
    echo ""
    echo "Examples:"
    echo "  $0 app my-app                      # Install all libs to default paths"
    echo "  $0 app my-app --python-only        # Only Python wheel"
    echo "  $0 app my-app --libs=auth          # Only @kamiwaza/auth package"
    echo "  $0 tool my-tool --py-path=src/     # Custom Python path"
    exit 0
}

# Parse arguments
TYPE=""
NAME=""
INSTALL_PYTHON=true
INSTALL_TS=true
LIBS=""  # Empty means all
PY_PATH_OVERRIDE=""
TS_PATH_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        app|service|tool)
            if [[ -z "$TYPE" ]]; then
                TYPE="$1"
            elif [[ -z "$NAME" ]]; then
                NAME="$1"
            else
                echo -e "${RED}Error: Unexpected argument: $1${NC}"
                usage
            fi
            shift
            ;;
        --python-only)
            INSTALL_TS=false
            shift
            ;;
        --ts-only)
            INSTALL_PYTHON=false
            shift
            ;;
        --libs=*)
            LIBS="${1#*=}"
            shift
            ;;
        --py-path=*)
            PY_PATH_OVERRIDE="${1#*=}"
            shift
            ;;
        --ts-path=*)
            TS_PATH_OVERRIDE="${1#*=}"
            shift
            ;;
        -h|--help)
            usage
            ;;
        -*)
            echo -e "${RED}Error: Unknown option: $1${NC}"
            usage
            ;;
        *)
            if [[ -z "$TYPE" ]]; then
                echo -e "${RED}Error: First argument must be 'app' or 'tool', got: $1${NC}"
                usage
            elif [[ -z "$NAME" ]]; then
                NAME="$1"
            else
                echo -e "${RED}Error: Unexpected argument: $1${NC}"
                usage
            fi
            shift
            ;;
    esac
done

# Validate required parameters
validate_params() {
    if [[ -z "$TYPE" ]]; then
        echo -e "${RED}Error: Extension type required (app, service, or tool)${NC}"
        usage
    fi

    if [[ "$TYPE" != "app" && "$TYPE" != "service" && "$TYPE" != "tool" ]]; then
        echo -e "${RED}Error: Type must be 'app', 'service', or 'tool', got: $TYPE${NC}"
        exit 1
    fi

    if [[ -z "$NAME" ]]; then
        echo -e "${RED}Error: Extension name required${NC}"
        usage
    fi

    # Validate extension exists
    local ext_path="${REPO_ROOT}/${TYPE}s/${NAME}"
    if [[ ! -d "$ext_path" ]]; then
        echo -e "${RED}Error: Extension not found: ${TYPE}s/${NAME}${NC}"
        echo "  Path checked: $ext_path"
        exit 1
    fi
}

# Validate install path exists
validate_install_path() {
    local path=$1
    local type=$2  # "Python" or "TypeScript"

    if [[ ! -d "$path" ]]; then
        echo -e "${RED}Error: $type install path does not exist: $path${NC}"
        echo ""
        echo "Ensure the directory exists before installing libraries."
        if [[ "$TYPE" == "app" ]]; then
            echo "For apps, this is typically:"
            echo "  - backend/ for Python"
            echo "  - frontend/ for TypeScript"
        elif [[ "$TYPE" == "service" ]]; then
            echo "For services, this is typically:"
            echo "  - root/ for Python"
        fi
        exit 1
    fi
}

# Validate Python packages have been built
validate_python_built() {
    if [[ ! -d "$PYTHON_DIST" ]]; then
        echo -e "${RED}Error: Python packages not built${NC}"
        echo "  Expected: $PYTHON_DIST"
        echo ""
        echo "Run 'make package-libs' first to build shared libraries."
        exit 1
    fi

    local wheel_count
    wheel_count=$(find "$PYTHON_DIST" -maxdepth 1 -name "*.whl" 2>/dev/null | wc -l)
    if [[ "$wheel_count" -eq 0 ]]; then
        echo -e "${RED}Error: No Python wheel files found in $PYTHON_DIST${NC}"
        echo ""
        echo "Run 'make package-libs' first to build shared libraries."
        exit 1
    fi
}

# Validate TypeScript package is built
validate_ts_package_built() {
    local pkg_name=$1
    local pkg_dir="${TS_SHARED_DIR}/${pkg_name}"

    if [[ ! -d "$pkg_dir" ]]; then
        echo -e "${RED}Error: TypeScript package not found: $pkg_name${NC}"
        echo "  Path checked: $pkg_dir"
        exit 1
    fi

    local tgz_count
    tgz_count=$(find "$pkg_dir" -maxdepth 1 -name "*.tgz" 2>/dev/null | wc -l)
    if [[ "$tgz_count" -eq 0 ]]; then
        echo -e "${RED}Error: No tgz files found for $pkg_name${NC}"
        echo "  Path: $pkg_dir"
        echo ""
        echo "Run 'make package-libs' first to build shared libraries."
        exit 1
    fi
}

# Resolve default Python path based on type
get_default_python_path() {
    local ext_path="${REPO_ROOT}/${TYPE}s/${NAME}"

    if [[ "$TYPE" == "app" ]]; then
        echo "${ext_path}/backend"
    else
        # Tools install at root
        echo "${ext_path}"
    fi
}

# Resolve default TypeScript path based on type
get_default_ts_path() {
    local ext_path="${REPO_ROOT}/${TYPE}s/${NAME}"

    if [[ "$TYPE" == "app" ]]; then
        echo "${ext_path}/frontend"
    else
        # Tools install at root
        echo "${ext_path}"
    fi
}

# Resolve final Python install path
resolve_python_path() {
    if [[ -n "$PY_PATH_OVERRIDE" ]]; then
        # Handle relative or absolute paths
        if [[ "$PY_PATH_OVERRIDE" == /* ]]; then
            echo "$PY_PATH_OVERRIDE"
        else
            echo "${REPO_ROOT}/${TYPE}s/${NAME}/${PY_PATH_OVERRIDE}"
        fi
    else
        get_default_python_path
    fi
}

# Resolve final TypeScript install path
resolve_ts_path() {
    if [[ -n "$TS_PATH_OVERRIDE" ]]; then
        # Handle relative or absolute paths
        if [[ "$TS_PATH_OVERRIDE" == /* ]]; then
            echo "$TS_PATH_OVERRIDE"
        else
            echo "${REPO_ROOT}/${TYPE}s/${NAME}/${TS_PATH_OVERRIDE}"
        fi
    else
        get_default_ts_path
    fi
}

# Parse LIBS parameter into array of package short names
parse_libs() {
    if [[ -z "$LIBS" ]]; then
        # Return all known packages
        get_all_short_names
    else
        # Split comma-separated list
        echo "$LIBS" | tr ',' ' '
    fi
}

# Install Python wheel
install_python() {
    local target_path=$1

    echo -e "${BLUE}Installing Python wheel...${NC}"

    validate_install_path "$target_path" "Python"
    validate_python_built

    # Find the latest wheel (most recently modified)
    local wheel_file
    wheel_file=$(find "$PYTHON_DIST" -maxdepth 1 -name "*.whl" -print0 | xargs -0 ls -t 2>/dev/null | head -1)
    local wheel_name
    wheel_name=$(basename "$wheel_file")

    # Copy wheel to target
    cp "$wheel_file" "$target_path/"

    echo -e "  ${GREEN}Copied: ${wheel_name}${NC}"
    echo -e "  ${GREEN}     -> ${target_path}/${NC}"
}

# Install a single TypeScript package
install_ts_package() {
    local pkg_short_name=$1
    local target_path=$2

    # Map short name to directory name
    local pkg_dir_name
    pkg_dir_name=$(map_short_to_dir "$pkg_short_name")

    if [[ -z "$pkg_dir_name" ]]; then
        echo -e "${YELLOW}Warning: Unknown package: $pkg_short_name (skipping)${NC}"
        echo "  Known packages: $(get_all_short_names)"
        return 0
    fi

    local pkg_dir="${TS_SHARED_DIR}/${pkg_dir_name}"

    validate_ts_package_built "$pkg_dir_name"

    # Find the latest tgz (most recently modified)
    local tgz_file
    tgz_file=$(find "$pkg_dir" -maxdepth 1 -name "*.tgz" -print0 | xargs -0 ls -t 2>/dev/null | head -1)
    local tgz_name
    tgz_name=$(basename "$tgz_file")

    # Copy tgz to target
    cp "$tgz_file" "$target_path/"

    echo -e "  ${GREEN}Copied: ${tgz_name}${NC}"
    echo -e "  ${GREEN}     -> ${target_path}/${NC}"
}

# Detect package manager in target directory
detect_package_manager() {
    local target_path=$1
    local pkg_json="${target_path}/package.json"

    if [[ ! -f "$pkg_json" ]]; then
        echo ""
        return 0
    fi

    # Check for pnpm-lock.yaml first (pnpm)
    if [[ -f "${target_path}/pnpm-lock.yaml" ]]; then
        echo "pnpm"
        return 0
    fi

    # Check for yarn.lock (yarn)
    if [[ -f "${target_path}/yarn.lock" ]]; then
        echo "yarn"
        return 0
    fi

    # Check for package-lock.json (npm)
    if [[ -f "${target_path}/package-lock.json" ]]; then
        echo "npm"
        return 0
    fi

    # Default to npm if package.json exists but no lockfile
    echo "npm"
}

# Update lockfile after installing TypeScript packages
update_lockfile() {
    local target_path=$1
    local pkg_manager
    pkg_manager=$(detect_package_manager "$target_path")

    if [[ -z "$pkg_manager" ]]; then
        return 0
    fi

    echo -e "${BLUE}Updating lockfile (using $pkg_manager)...${NC}"

    cd "$target_path"

    case "$pkg_manager" in
        pnpm)
            if command -v pnpm >/dev/null 2>&1 || command -v corepack >/dev/null 2>&1; then
                if command -v corepack >/dev/null 2>&1; then
                    corepack enable >/dev/null 2>&1 || true
                fi
                # Use --no-frozen-lockfile to allow updating the lockfile
                pnpm install --no-frozen-lockfile >/dev/null 2>&1 || {
                    echo -e "${YELLOW}Warning: Failed to update pnpm-lock.yaml automatically${NC}"
                    echo -e "${YELLOW}         Run 'pnpm install' manually to update the lockfile${NC}"
                }
            else
                echo -e "${YELLOW}Warning: pnpm not found. Run 'pnpm install' manually to update the lockfile${NC}"
            fi
            ;;
        yarn)
            if command -v yarn >/dev/null 2>&1; then
                # Use --no-frozen-lockfile to allow updating the lockfile
                yarn install --no-frozen-lockfile >/dev/null 2>&1 || {
                    echo -e "${YELLOW}Warning: Failed to update yarn.lock automatically${NC}"
                    echo -e "${YELLOW}         Run 'yarn install' manually to update the lockfile${NC}"
                }
            else
                echo -e "${YELLOW}Warning: yarn not found. Run 'yarn install' manually to update the lockfile${NC}"
            fi
            ;;
        npm)
            if command -v npm >/dev/null 2>&1; then
                # Use --package-lock-only to update lockfile without installing
                npm install --package-lock-only >/dev/null 2>&1 || {
                    echo -e "${YELLOW}Warning: Failed to update package-lock.json automatically${NC}"
                    echo -e "${YELLOW}         Run 'npm install' manually to update the lockfile${NC}"
                }
            else
                echo -e "${YELLOW}Warning: npm not found. Run 'npm install' manually to update the lockfile${NC}"
            fi
            ;;
    esac

    echo -e "  ${GREEN}Lockfile updated${NC}"
}

# Install TypeScript packages
install_typescript() {
    local target_path=$1

    echo -e "${BLUE}Installing TypeScript packages...${NC}"

    validate_install_path "$target_path" "TypeScript"

    local packages
    packages=$(parse_libs)
    local installed_count=0

    for pkg in $packages; do
        install_ts_package "$pkg" "$target_path"
        ((installed_count++)) || true
    done

    if [[ $installed_count -eq 0 ]]; then
        echo -e "${YELLOW}No TypeScript packages installed${NC}"
        return 0
    fi

    # Automatically update lockfile after installing packages
    # This prevents integrity checksum mismatches when tarballs are regenerated
    update_lockfile "$target_path"
}

# Print summary and next steps
print_summary() {
    local py_path=$1
    local ts_path=$2

    echo ""
    echo -e "${GREEN}=== Installation Complete ===${NC}"
    echo ""

    echo -e "${BOLD}${CYAN}Installed to:${NC}"
    if [[ "$INSTALL_PYTHON" == "true" ]]; then
        echo -e "  Python:     $py_path"
    fi
    if [[ "$INSTALL_TS" == "true" ]]; then
        echo -e "  TypeScript: $ts_path"
    fi
    echo ""

    echo -e "${BOLD}${CYAN}Next Steps:${NC}"
    echo ""

    if [[ "$INSTALL_PYTHON" == "true" ]]; then
        local wheel_name
        wheel_name=$(find "$PYTHON_DIST" -maxdepth 1 -name "*.whl" -print0 | xargs -0 ls -t 2>/dev/null | head -1 | xargs basename)
        echo -e "${BOLD}Python (requirements.txt):${NC}"
        echo -e "  Add to the top of your requirements.txt:"
        echo -e "  ${YELLOW}# Kamiwaza shared library (bundled wheel)"
        echo -e "  ./${wheel_name}${NC}"
        echo ""
    fi

    if [[ "$INSTALL_TS" == "true" ]]; then
        echo -e "${BOLD}TypeScript (package.json):${NC}"
        echo -e "  Add to dependencies in package.json:"

        local packages
        packages=$(parse_libs)
        for pkg in $packages; do
            local pkg_dir_name
            pkg_dir_name=$(map_short_to_dir "$pkg")
            if [[ -n "$pkg_dir_name" ]]; then
                local pkg_dir="${TS_SHARED_DIR}/${pkg_dir_name}"
                local npm_name
                npm_name=$(cd "$pkg_dir" && node -p "require('./package.json').name" 2>/dev/null || echo "@kamiwaza/$pkg")
                local tgz_name
                tgz_name=$(find "$pkg_dir" -maxdepth 1 -name "*.tgz" -print0 | xargs -0 ls -t 2>/dev/null | head -1 | xargs basename)
                echo -e "  ${YELLOW}\"$npm_name\": \"file:./${tgz_name}\"${NC}"
            fi
        done
        echo ""
        local pkg_manager
        pkg_manager=$(detect_package_manager "$ts_path")
        if [[ -n "$pkg_manager" ]]; then
            echo -e "  ${GREEN}✓ Lockfile updated automatically${NC}"
        else
            echo "  Then run:"
            echo -e "  ${YELLOW}npm install${NC}  # (or pnpm install / yarn install)"
        fi
        echo ""
    fi
}

# Main execution
main() {
    echo -e "${BLUE}=== Installing Shared Libraries ===${NC}"
    echo ""

    validate_params

    local py_path
    py_path=$(resolve_python_path)
    local ts_path
    ts_path=$(resolve_ts_path)

    echo "Extension: ${TYPE}s/${NAME}"
    if [[ "$INSTALL_PYTHON" == "true" ]]; then
        echo "Python target: $py_path"
    fi
    if [[ "$INSTALL_TS" == "true" ]]; then
        echo "TypeScript target: $ts_path"
    fi
    if [[ -n "$LIBS" ]]; then
        echo "Selected packages: $LIBS"
    fi
    echo ""

    if [[ "$INSTALL_PYTHON" == "true" ]]; then
        install_python "$py_path"
    fi

    if [[ "$INSTALL_TS" == "true" ]]; then
        install_typescript "$ts_path"
    fi

    print_summary "$py_path" "$ts_path"
}

main
