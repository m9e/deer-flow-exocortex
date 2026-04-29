#!/bin/bash
#
# Run tests for extensions
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Use docker compose v2 syntax if available, fallback to docker-compose
docker_compose() {
    if docker compose version &>/dev/null; then
        docker compose "$@"
    else
        docker-compose "$@"
    fi
}

# Parse arguments
TYPE="${1:-}"
NAME="${2:-}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Track services we started
SERVICES_STARTED=""
SERVICES_PATH=""
MOCK_LLM_PID=""

# Check if required ports are available
check_ports() {
    local ports_in_use=()

    # Check port 11435 (mock LLM server)
    if lsof -ti:11435 >/dev/null 2>&1; then
        ports_in_use+=("11435")
    fi

    # Check port 13013 (Next.js dev server)
    if lsof -ti:13013 >/dev/null 2>&1; then
        ports_in_use+=("13013")
    fi

    if [[ ${#ports_in_use[@]} -gt 0 ]]; then
        echo -e "${RED}✗ Required ports are already in use:${NC}"
        for port in "${ports_in_use[@]}"; do
            echo -e "  ${YELLOW}Port $port:${NC}"
            lsof -i:$port | grep LISTEN || true
        done
        echo ""
        echo -e "${BLUE}To clean up, run:${NC}"
        echo -e "  ${YELLOW}lsof -ti:11435,13013 | xargs kill -9${NC}"
        echo ""
        return 1
    fi
    return 0
}

# Cleanup function
cleanup_services() {
    # Stop mock LLM server if we started it
    if [[ -n "$MOCK_LLM_PID" ]]; then
        echo -e "\n${BLUE}Stopping mock LLM server...${NC}"
        kill $MOCK_LLM_PID 2>/dev/null || true
        wait $MOCK_LLM_PID 2>/dev/null || true
    fi

    # Kill any remaining processes on test ports
    echo -e "${BLUE}Cleaning up test ports...${NC}"
    lsof -ti:11435,13013 2>/dev/null | xargs kill -9 2>/dev/null || true

    # Stop docker services if we started them
    if [[ -n "$SERVICES_STARTED" ]] && [[ -n "$SERVICES_PATH" ]]; then
        echo -e "${BLUE}Stopping dev services...${NC}"
        cd "$SERVICES_PATH"
        docker_compose -f dev-docker-compose.yml down
    fi
}

# Set trap to cleanup on exit
trap cleanup_services EXIT INT TERM

usage() {
    echo "Usage: $0 <type> <name>"
    echo "       $0 all"
    echo ""
    echo "Examples:"
    echo "  $0 app kaizen-app     # Test specific app"
    echo "  $0 service service-milvus # Test specific service"
    echo "  $0 tool websearch-tool # Test specific tool"
    echo "  $0 all                # Test all extensions"
    exit 1
}

# Function to detect and run tests
run_tests() {
    local test_path=$1
    local ext_name=$(basename $(dirname "$test_path"))

    echo -e "${BLUE}Testing ${ext_name}...${NC}"

    cd "$test_path"

    # Check if required ports are available before starting
    if [[ -f "package.json" ]] && grep -q "@playwright/test" package.json; then
        if ! check_ports; then
            echo -e "${RED}✗ Cannot start tests - ports in use${NC}"
            return 1
        fi
    fi

    # Python tests (pytest)
    if [[ -f "requirements.txt" ]] || [[ -f "pyproject.toml" ]]; then
        # Prefer project-local venv pytest (has dev deps like pytest-cov)
        local pytest_cmd=""
        if [[ -x "${REPO_ROOT}/.venv/bin/pytest" ]]; then
            pytest_cmd="${REPO_ROOT}/.venv/bin/pytest"
        elif command -v pytest &> /dev/null; then
            pytest_cmd="pytest"
        fi
        if [[ -n "$pytest_cmd" ]]; then
            echo "  Running Python tests with coverage..."
            if "$pytest_cmd" --cov --cov-report=term-missing; then
                echo -e "${GREEN}✓ Python tests passed${NC}"
                return 0
            else
                echo -e "${RED}✗ Python tests failed${NC}"
                return 1
            fi
        elif [[ -f "test_*.py" ]] || [[ -d "tests" ]]; then
            echo "  Running Python tests with unittest..."
            if python3 -m unittest discover; then
                echo -e "${GREEN}✓ Python tests passed${NC}"
                return 0
            else
                echo -e "${RED}✗ Python tests failed${NC}"
                return 1
            fi
        else
            echo -e "${YELLOW}⚠ No Python tests found${NC}"
            return 0
        fi
    fi

    # Node.js tests
    if [[ -f "package.json" ]]; then
        # Install dependencies if node_modules doesn't exist
        if [[ ! -d "node_modules" ]]; then
            echo "  Installing dependencies..."
            if [[ -f "pnpm-lock.yaml" ]]; then
                pnpm install --frozen-lockfile
            elif [[ -f "package-lock.json" ]]; then
                npm ci
            elif [[ -f "yarn.lock" ]]; then
                yarn install --frozen-lockfile
            else
                npm install
            fi
        fi

        # If playwright is in dependencies, ensure browsers are installed
        # (playwright install is idempotent - skips download if already present)
        if grep -q "@playwright/test" package.json; then
            echo "  Ensuring Playwright browsers are installed..."
            npx playwright install --with-deps
        fi

        # Start dev services if dev-docker-compose.yml exists
        if [[ -f "dev-docker-compose.yml" ]]; then
            echo "  Starting dev services..."
            docker_compose -f dev-docker-compose.yml up -d

            # Track that we started services
            SERVICES_STARTED="yes"
            SERVICES_PATH="$test_path"

            # Wait for services to be healthy
            echo "  Waiting for services to be ready..."
            local max_wait=30
            local count=0
            while [[ $count -lt $max_wait ]]; do
                if docker_compose -f dev-docker-compose.yml ps | grep -q "healthy\|Up"; then
                    echo "  Services ready!"
                    break
                fi
                sleep 1
                ((count++))
            done

            if [[ $count -ge $max_wait ]]; then
                echo -e "${YELLOW}⚠ Services may not be fully ready${NC}"
            fi

            # Run database migrations if db:migrate script exists
            if grep -q '"db:migrate"' package.json; then
                echo "  Running database migrations..."
                # Load .env.test for migration
                if [[ -f ".env.test" ]]; then
                    export $(cat .env.test | grep -v '^#' | xargs)
                fi
                if npm run db:migrate; then
                    echo "  Migrations completed!"
                else
                    echo -e "${YELLOW}⚠ Migration failed or had issues${NC}"
                fi
            fi
        fi

        # Start mock LLM server if tests/mock-llm-server.ts exists
        if [[ -f "tests/mock-llm-server.ts" ]] && grep -q "@playwright/test" package.json; then
            echo "  Starting mock LLM server..."
            npx tsx tests/mock-llm-server.ts &
            MOCK_LLM_PID=$!
            echo "  Mock LLM server started (PID: $MOCK_LLM_PID)"
            # Wait for server to be ready
            sleep 2
        fi

        # Check for test:coverage script first, then test
        if grep -q '"test:coverage"' package.json; then
            echo "  Running Node.js tests with coverage..."
            if npm run test:coverage; then
                echo -e "${GREEN}✓ Node.js tests passed${NC}"
                return 0
            else
                echo -e "${RED}✗ Node.js tests failed${NC}"
                return 1
            fi
        elif grep -q '"test"' package.json; then
            echo "  Running Node.js tests..."
            if npm test; then
                echo -e "${GREEN}✓ Node.js tests passed${NC}"
                return 0
            else
                echo -e "${RED}✗ Node.js tests failed${NC}"
                return 1
            fi
        else
            echo -e "${YELLOW}⚠ No test script in package.json${NC}"
            return 0
        fi
    fi

    # Go tests
    if [[ -f "go.mod" ]]; then
        echo "  Running Go tests..."
        if go test ./...; then
            echo -e "${GREEN}✓ Go tests passed${NC}"
            return 0
        else
            echo -e "${RED}✗ Go tests failed${NC}"
            return 1
        fi
    fi

    echo -e "${YELLOW}⚠ No recognized test framework found${NC}"
    return 0
}

# Function to test an extension
test_extension() {
    local ext_type=$1
    local ext_name=$2
    local ext_path="${REPO_ROOT}/${ext_type}s/${ext_name}"

    if [[ ! -d "$ext_path" ]]; then
        echo -e "${RED}Error: Extension not found: ${ext_type}s/${ext_name}${NC}"
        return 1
    fi

    echo -e "\n${BLUE}=== Testing ${ext_type}/${ext_name} ===${NC}"

    # Check for tests directory
    if [[ -d "$ext_path/tests" ]]; then
        run_tests "$ext_path"
    elif [[ -d "$ext_path/test" ]]; then
        run_tests "$ext_path"
    else
        # Check for test files in root
        cd "$ext_path"
        if ls test_*.py &> /dev/null || ls *_test.go &> /dev/null || [[ -f "package.json" ]]; then
            run_tests "$ext_path"
        else
            # Check subdirectories for tests
            local found_tests=false
            for subdir in "$ext_path"/*; do
                if [[ -d "$subdir" ]] && [[ -d "$subdir/tests" || -d "$subdir/test" ]]; then
                    echo -e "\n  Testing $(basename "$subdir")..."
                    run_tests "$subdir"
                    found_tests=true
                fi
            done

            if [[ "$found_tests" == "false" ]]; then
                echo -e "${YELLOW}⚠ No tests found${NC}"
            fi
        fi
    fi

    # Run frontend tests if a frontend package exists (e.g., apps with frontend/ subdir)
    if [[ -d "$ext_path/frontend" ]] && [[ -f "$ext_path/frontend/package.json" ]]; then
        echo -e "\n  Running frontend tests..."
        run_tests "$ext_path/frontend"
    fi
}

# Function to test all extensions
test_all() {
    echo "Testing all extensions..."
    local failed_count=0

    # Test all apps
    if [[ -d "${REPO_ROOT}/apps" ]]; then
        for app_path in "${REPO_ROOT}/apps"/*; do
            if [[ -d "$app_path" ]] && [[ ! "$(basename "$app_path")" =~ ^\. ]]; then
                if ! test_extension "app" "$(basename "$app_path")"; then
                    ((failed_count++))
                fi
            fi
        done
    fi

    # Test all services
    if [[ -d "${REPO_ROOT}/services" ]]; then
        for service_path in "${REPO_ROOT}/services"/*; do
            if [[ -d "$service_path" ]] && [[ ! "$(basename "$service_path")" =~ ^\. ]]; then
                if ! test_extension "service" "$(basename "$service_path")"; then
                    ((failed_count++))
                fi
            fi
        done
    fi

    # Test all tools
    if [[ -d "${REPO_ROOT}/tools" ]]; then
        for tool_path in "${REPO_ROOT}/tools"/*; do
            if [[ -d "$tool_path" ]] && [[ ! "$(basename "$tool_path")" =~ ^\. ]]; then
                if ! test_extension "tool" "$(basename "$tool_path")"; then
                    ((failed_count++))
                fi
            fi
        done
    fi

    echo -e "\n${BLUE}=== Test Summary ===${NC}"
    if [[ $failed_count -eq 0 ]]; then
        echo -e "${GREEN}✓ All tests passed!${NC}"
        return 0
    else
        echo -e "${RED}✗ $failed_count extension(s) failed tests${NC}"
        return 1
    fi
}

# Main logic
if [[ "$TYPE" == "all" ]]; then
    test_all
elif [[ -n "$TYPE" ]] && [[ -n "$NAME" ]]; then
    test_extension "$TYPE" "$NAME"
else
    usage
fi
