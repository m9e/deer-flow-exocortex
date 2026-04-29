#!/bin/bash
#
# Integration tests for Kamiwaza Extensions scripts
#
# This script tests all the automation tools and cleans up after itself.
# It creates temporary test extensions, verifies functionality, then removes them.
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
NC='\033[0m'

# Test state
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
TEST_ARTIFACTS=()
VERBOSE="${VERBOSE:-false}"

# Error handler
cleanup() {
    local exit_code=$?
    echo -e "\n${CYAN}Cleaning up test artifacts...${NC}"

    # Remove test extensions
    for artifact in "${TEST_ARTIFACTS[@]}"; do
        if [[ -e "$artifact" ]]; then
            rm -rf "$artifact"
            echo "  Removed: $artifact"
        fi
    done

    # Report results
    echo -e "\n${CYAN}Test Summary:${NC}"
    echo "  Tests run: $TESTS_RUN"
    echo -e "  ${GREEN}Passed: $TESTS_PASSED${NC}"
    if [[ $TESTS_FAILED -gt 0 ]]; then
        echo -e "  ${RED}Failed: $TESTS_FAILED${NC}"
    fi

    exit $exit_code
}

trap cleanup EXIT

# Test functions
run_test() {
    local test_name=$1
    local test_cmd=$2

    TESTS_RUN=$((TESTS_RUN + 1))
    echo -e "\n${BLUE}TEST: $test_name${NC}"

    if [[ "$VERBOSE" == "true" ]]; then
        # In verbose mode, show test output
        if eval "$test_cmd"; then
            echo -e "${GREEN}✓ PASS${NC}"
            TESTS_PASSED=$((TESTS_PASSED + 1))
        else
            echo -e "${RED}✗ FAIL${NC}"
            TESTS_FAILED=$((TESTS_FAILED + 1))
        fi
    else
        # In quiet mode, capture output
        if output=$(eval "$test_cmd" 2>&1); then
            echo -e "${GREEN}✓ PASS${NC}"
            TESTS_PASSED=$((TESTS_PASSED + 1))
        else
            echo -e "${RED}✗ FAIL${NC}"
            TESTS_FAILED=$((TESTS_FAILED + 1))
            echo -e "${YELLOW}  Output: ${output:0:100}...${NC}"
        fi
    fi
}

# Test 1: verify-images.py help
test_verify_images_help() {
    python3 "$SCRIPT_DIR/verify-images.py" --help > /dev/null 2>&1
}

# Test 2: verify-images.py local mode
test_verify_images_local() {
    # Test that it runs and produces expected output format
    output=$(python3 "$SCRIPT_DIR/verify-images.py" 2>&1)
    echo "$output" | grep -q "Verifying Docker images" && \
    echo "$output" | grep -q "Mode: Local" && \
    echo "$output" | grep -q "Summary:" && \
    echo "$output" | grep -q "✅ Verified:" && \
    echo "$output" | grep -q "❌ Missing:"
    # Note: We don't check exit code as it may fail due to missing images
}

# Test 3: validate-metadata.py
test_validate_metadata() {
    python3 "$SCRIPT_DIR/validate-metadata.py" > /dev/null 2>&1
}

# Test 4: Create internal extension
test_create_internal() {
    cd "$REPO_ROOT"
    make new-internal TYPE=app NAME=test-internal-app > /dev/null 2>&1
    TEST_ARTIFACTS+=("$REPO_ROOT/apps/test-internal-app")

    # Verify structure
    [[ -d "$REPO_ROOT/apps/test-internal-app" ]] && \
    [[ -f "$REPO_ROOT/apps/test-internal-app/README.md" ]]
}

# Test 5: Create internal service extension
test_create_internal_service() {
    cd "$REPO_ROOT"
    make new-internal TYPE=service NAME=test-internal-service > /dev/null 2>&1
    TEST_ARTIFACTS+=("$REPO_ROOT/services/test-internal-service")

    # Verify structure
    [[ -d "$REPO_ROOT/services/test-internal-service" ]] && \
    [[ -f "$REPO_ROOT/services/test-internal-service/README.md" ]]
}

# Test 6: Create external extension
test_create_external() {
    cd "$REPO_ROOT"
    make new-external TYPE=tool NAME=test-external-tool > /dev/null 2>&1
    TEST_ARTIFACTS+=("$REPO_ROOT/tools/test-external-tool")

    # Verify structure
    [[ -d "$REPO_ROOT/tools/test-external-tool" ]] && \
    [[ -f "$REPO_ROOT/tools/test-external-tool/README.md" ]] && \
    grep -q "External Extension" "$REPO_ROOT/tools/test-external-tool/README.md"
}

# Test 7: Create hybrid extension
test_create_hybrid() {
    cd "$REPO_ROOT"
    make new-hybrid TYPE=app NAME=test-hybrid-app > /dev/null 2>&1
    TEST_ARTIFACTS+=("$REPO_ROOT/apps/test-hybrid-app")

    # Verify structure
    [[ -d "$REPO_ROOT/apps/test-hybrid-app" ]] && \
    [[ -f "$REPO_ROOT/apps/test-hybrid-app/README.md" ]] && \
    grep -q "Hybrid Extension" "$REPO_ROOT/apps/test-hybrid-app/README.md"
}

# Test 8: External extension with build script
test_external_build() {
    # Create a proper external extension
    local ext_path="$REPO_ROOT/apps/test-external-build"
    mkdir -p "$ext_path"
    TEST_ARTIFACTS+=("$ext_path")

    # Add metadata
    cat > "$ext_path/kamiwaza.json" <<EOF
{
  "name": "test-external-build",
  "version": "1.0.0",
  "source_type": "kamiwaza",
  "visibility": "public",
  "description": "Test external build",
  "risk_tier": 0,
  "verified": false
}
EOF

    # Add compose file
    cat > "$ext_path/docker-compose.appgarden.yml" <<EOF
version: '3.9'
services:
  app:
    image: nginx:alpine
    ports:
      - "80"
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: "256M"
EOF

    # Test build command
    cd "$REPO_ROOT"
    output=$(make build TYPE=app NAME=test-external-build 2>&1)
    # Check for expected external extension behavior
    echo "$output" | grep -q "No Dockerfile found - checking for external images" && \
    echo "$output" | grep -q "External extension - verifying images" && \
    echo "$output" | grep -q "nginx:alpine"
}

# Test 9: publish-images.sh dry run
test_publish_dry_run() {
    output=$("$SCRIPT_DIR/publish-images.sh" --dry-run 2>&1)
    # Verify dry run mode message and that it processes extensions
    echo "$output" | grep -q "DRY RUN MODE" && \
    echo "$output" | grep -q "Processing" && \
    echo "$output" | grep -q "Skipping.*no local source"
}

# Test 10: sync-compose functionality
test_sync_compose() {
    # Create app with docker-compose.yml
    local ext_path="$REPO_ROOT/apps/test-sync-compose"
    mkdir -p "$ext_path"
    TEST_ARTIFACTS+=("$ext_path")

    # Add metadata
    cat > "$ext_path/kamiwaza.json" <<EOF
{
  "name": "test-sync-compose",
  "version": "1.0.0",
  "source_type": "kamiwaza",
  "visibility": "public",
  "description": "Test sync compose",
  "risk_tier": 0,
  "verified": false
}
EOF

    # Add docker-compose.yml
    cat > "$ext_path/docker-compose.yml" <<EOF
version: '3.9'
services:
  app:
    build: .
    image: test/app:latest
    ports:
      - "8080:8080"
    volumes:
      - ./src:/app
EOF

    # Run sync
    cd "$REPO_ROOT"
    python3 "$SCRIPT_DIR/sync-compose.py" --type app --name test-sync-compose > /dev/null 2>&1

    # Verify appgarden file was created and has no build context
    [[ -f "$ext_path/docker-compose.appgarden.yml" ]] && \
    ! grep -q "build:" "$ext_path/docker-compose.appgarden.yml" && \
    grep -q "image: test/app:latest" "$ext_path/docker-compose.appgarden.yml"
}

# Test 11: build-registry.py
test_build_registry() {
    # Just ensure it runs without error
    python3 "$SCRIPT_DIR/build-registry.py" > /dev/null 2>&1

    # Verify output files exist
    [[ -f "$REPO_ROOT/build/garden/default/apps.json" ]] && \
    [[ -f "$REPO_ROOT/build/garden/default/tools.json" ]]
}

# Test 12: Image verification with missing Dockerfile
test_missing_dockerfile_handling() {
    # This tests the enhancement we made to build-extension.sh
    local ext_path="$REPO_ROOT/tools/test-no-dockerfile"
    mkdir -p "$ext_path"
    TEST_ARTIFACTS+=("$ext_path")

    # Add metadata
    cat > "$ext_path/kamiwaza.json" <<EOF
{
  "name": "test-no-dockerfile",
  "version": "1.0.0",
  "source_type": "kamiwaza",
  "visibility": "public",
  "description": "Test missing Dockerfile",
  "image": "alpine:latest",
  "risk_tier": 0,
  "verified": false
}
EOF

    # Run build - should detect external
    cd "$REPO_ROOT"
    output=$("$SCRIPT_DIR/build-extension.sh" tool test-no-dockerfile 2>&1)
    echo "$output" | grep -q "No Dockerfile found - checking for external images"
}

# Test 13: Validate all test extensions
test_validate_with_test_extensions() {
    # Validate should still work with test extensions present
    cd "$REPO_ROOT"
    output=$(python3 "$SCRIPT_DIR/validate-metadata.py" 2>&1)
    # Should validate successfully or at least run without crashing
    echo "$output" | grep -q "Validating extension metadata" && \
    echo "$output" | grep -q "Validating apps..." && \
    echo "$output" | grep -q "Validating services..." && \
    echo "$output" | grep -q "Validating tools..."
}

# Main execution
main() {
    echo -e "${CYAN}Running Kamiwaza Extensions Integration Tests${NC}"
    echo "=============================================="

    # Clean up any leftover test artifacts from previous runs
    echo -e "${CYAN}Cleaning up any previous test artifacts...${NC}"
    rm -rf "$REPO_ROOT/apps/test-"* "$REPO_ROOT/services/test-"* "$REPO_ROOT/tools/test-"* 2>/dev/null || true

    # Core script tests
    run_test "verify-images.py --help" test_verify_images_help
    run_test "verify-images.py local mode" test_verify_images_local
    run_test "validate-metadata.py" test_validate_metadata

    # Template tests
    run_test "Create internal extension" test_create_internal
    run_test "Create internal service extension" test_create_internal_service
    run_test "Create external extension" test_create_external
    run_test "Create hybrid extension" test_create_hybrid

    # Build and publish tests
    run_test "Build external extension" test_external_build
    run_test "publish-images.sh --dry-run" test_publish_dry_run

    # Compose sync test
    run_test "sync-compose.py" test_sync_compose

    # Registry generation
    run_test "build-registry.py" test_build_registry

    # Edge case tests
    run_test "Missing Dockerfile handling" test_missing_dockerfile_handling
    run_test "Validate with test extensions" test_validate_with_test_extensions

    # Return appropriate exit code
    if [[ $TESTS_FAILED -gt 0 ]]; then
        return 1
    else
        return 0
    fi
}

# Run tests
main
