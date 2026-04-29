# build.mk - Build and test commands for extensions
#
# Commands for building, testing, and publishing extensions

ifndef _BUILD_MK_
_BUILD_MK_ := 1

# ==============================================================================
# Shared Libraries
# ==============================================================================

# Build shared library packages
# Usage:
#   make package-libs                    # Build all packages
#   make package-libs PYTHON_ONLY=1      # Build only Python wheel
#   make package-libs TS_ONLY=1          # Build only TypeScript package
#   make package-libs CLEAN=1            # Clean and rebuild all
.PHONY: package-libs
package-libs: ## Build shared libraries - options: PYTHON_ONLY=1, TS_ONLY=1, CLEAN=1
	@ARGS=""; \
	if [ "$(PYTHON_ONLY)" = "1" ]; then ARGS="$$ARGS --python-only"; fi; \
	if [ "$(TS_ONLY)" = "1" ]; then ARGS="$$ARGS --ts-only"; fi; \
	if [ "$(CLEAN)" = "1" ]; then ARGS="$$ARGS --clean"; fi; \
	./scripts/package-shared-libs.sh $$ARGS

# Install shared library packages into an extension
# Usage:
#   make install-libs TYPE=app NAME=my-app                  # Install all to default paths
#   make install-libs TYPE=tool NAME=my-tool PYTHON_ONLY=1  # Only Python wheel
#   make install-libs TYPE=app NAME=my-app TS_ONLY=1        # Only TypeScript packages
#   make install-libs TYPE=app NAME=my-app LIBS=auth        # Only auth package
#   make install-libs TYPE=app NAME=my-app PY_PATH=src/     # Custom Python path
.PHONY: install-libs
install-libs: ## Install shared libs - usage: make install-libs TYPE=app|service|tool NAME=name [PYTHON_ONLY=1] [TS_ONLY=1] [LIBS=auth,client] [PY_PATH=path] [TS_PATH=path]
	@if [ -z "$(TYPE)" ] || [ -z "$(NAME)" ]; then \
		echo "Error: TYPE and NAME are required"; \
		echo "Usage: make install-libs TYPE=app|service|tool NAME=name"; \
		exit 1; \
	fi; \
	ARGS="$(TYPE) $(NAME)"; \
	if [ "$(PYTHON_ONLY)" = "1" ]; then ARGS="$$ARGS --python-only"; fi; \
	if [ "$(TS_ONLY)" = "1" ]; then ARGS="$$ARGS --ts-only"; fi; \
	if [ -n "$(LIBS)" ]; then ARGS="$$ARGS --libs=$(LIBS)"; fi; \
	if [ -n "$(PY_PATH)" ]; then ARGS="$$ARGS --py-path=$(PY_PATH)"; fi; \
	if [ -n "$(TS_PATH)" ]; then ARGS="$$ARGS --ts-path=$(TS_PATH)"; fi; \
	./scripts/install-shared-libs.sh $$ARGS

# Install shared entrypoint scripts into an extension
# Usage:
#   make install-entrypoints TYPE=app NAME=my-app                    # Install all to default path
#   make install-entrypoints TYPE=app NAME=my-app SCRIPTS=kamiwaza-entrypoint.sh
#   make install-entrypoints TYPE=app NAME=my-app DEST=docker/scripts/
.PHONY: install-entrypoints
install-entrypoints: ## Install shared entrypoints - usage: make install-entrypoints TYPE=app NAME=name [SCRIPTS=list] [DEST=path]
	@if [ -z "$(TYPE)" ] || [ -z "$(NAME)" ]; then \
		echo "Error: TYPE and NAME are required"; \
		echo "Usage: make install-entrypoints TYPE=app|tool NAME=name"; \
		exit 1; \
	fi; \
	ARGS="$(TYPE) $(NAME)"; \
	if [ -n "$(SCRIPTS)" ]; then ARGS="$$ARGS --scripts=$(SCRIPTS)"; fi; \
	if [ -n "$(DEST)" ]; then ARGS="$$ARGS --path=$(DEST)"; fi; \
	./scripts/install-entrypoints.sh $$ARGS

# ==============================================================================
# Building and Testing
# ==============================================================================

.PHONY: build
build: ## Build extension - usage: make build TYPE=app NAME=kaizen-app
	@./scripts/build-extension.sh $(TYPE) $(NAME)

.PHONY: build-no-cache
build-no-cache: ## Build extension without cache - usage: make build-no-cache TYPE=app NAME=kaizen-app
	@./scripts/build-extension.sh $(TYPE) $(NAME) --no-cache

.PHONY: bump
bump: ## Bump version in kamiwaza.json - usage: make bump TYPE=app NAME=coe-app LEVEL=PATCH|MINOR|MAJOR
	@./scripts/bump-version.sh $(TYPE) $(NAME) $(LEVEL)

.PHONY: test
test: ## Test extensions with coverage - usage: make test [TYPE=app NAME=kaizen-app] (defaults to all)
	@if [ -z "$(TYPE)" ]; then \
		./scripts/test-extension.sh all; \
	else \
		./scripts/test-extension.sh $(TYPE) $(NAME); \
	fi

.PHONY: push
push: ## Push extension images - usage: make push TYPE=app NAME=my-app [STAGE=dev|stage|prod] [BUILD=1] [DRY_RUN=1]
	@if [ -z "$(TYPE)" ] || [ -z "$(NAME)" ]; then \
		echo "Error: TYPE and NAME are required"; \
		echo "Usage: make push TYPE=app|service|tool NAME=name [STAGE=dev|stage|prod] [BUILD=1] [DRY_RUN=1]"; \
		exit 1; \
	fi; \
	ARGS="--type $(TYPE) --name $(NAME) --stage $(STAGE)"; \
	if [ "$(BUILD)" = "1" ]; then ARGS="$$ARGS --build --platforms $(PLATFORMS)"; fi; \
	if [ "$(DRY_RUN)" = "1" ]; then ARGS="$$ARGS --dry-run"; fi; \
	STAGE=$(STAGE) PLATFORMS=$(PLATFORMS) ./scripts/publish-images.sh $$ARGS

.PHONY: build-all
build-all: ## Build all extensions
	@./scripts/build-extension.sh all

.PHONY: build-all-no-cache
build-all-no-cache: ## Build all extensions without cache
	@./scripts/build-extension.sh all --no-cache

.PHONY: test-all
test-all: ## Test all extensions
	@./scripts/test-extension.sh all

# ==============================================================================
# Integration Testing
# ==============================================================================

.PHONY: test-integration
test-integration: ## Run integration tests for all scripts
	@./scripts/test-integration.sh

.PHONY: test-integration-verbose
test-integration-verbose: ## Run integration tests with verbose output
	@VERBOSE=true ./scripts/test-integration.sh

.PHONY: test-scripts
test-scripts: test-integration ## Alias for test-integration

# ==============================================================================
# Publishing
# ==============================================================================

# Stage and version for publishing (inherited from metadata.mk if included)
STAGE ?= dev

# Multi-arch platforms for Docker builds
PLATFORMS ?= linux/amd64,linux/arm64

# Force flag for registry publishing (bypass version checks)
FORCE ?=

# Publish target: publishes BOTH registry files AND multi-arch Docker images
# Usage:
#   make publish                             # Publish to dev (default)
#   make publish STAGE=prod                  # Publish to production
#   make publish STAGE=stage REPO_VERSION=1  # Publish legacy format to staging
#   make publish PLATFORMS=linux/amd64       # Build for single platform only
#
# Multi-arch Docker images (default: linux/amd64,linux/arm64):
#   - Builds and pushes directly using docker buildx
#   - Creates multi-arch manifest automatically
#
# Stage-based tagging for Docker images:
#   - dev:   version-dev tag
#   - stage: version-stage tag
#   - prod:  version tag (no suffix)
#
# Registry files are uploaded to:
#   - dev:   https://dev-info.kamiwaza.ai/garden/{version}/
#   - stage: https://stage-info.kamiwaza.ai/garden/{version}/
#   - prod:  https://info.kamiwaza.ai/garden/{version}/

.PHONY: publish
publish: publish-registry publish-images ## Publish registry AND Docker images - usage: make publish [STAGE=dev|stage|prod] [REPO_VERSION=1|2|3]

.PHONY: publish-images
publish-images: ## Build and publish multi-arch Docker images - usage: make publish-images [STAGE=prod] [PLATFORMS=linux/amd64,linux/arm64]
	@STAGE=$(STAGE) PLATFORMS=$(PLATFORMS) ./scripts/publish-images.sh --build

.PHONY: publish-images-dry-run
publish-images-dry-run: ## Show what multi-arch images would be published (dry run)
	@STAGE=$(STAGE) PLATFORMS=$(PLATFORMS) ./scripts/publish-images.sh --build --dry-run

.PHONY: publish-images-single-arch
publish-images-single-arch: ## Verify and push single-arch images (legacy) - usage: make publish-images-single-arch [STAGE=dev|stage|prod]
	@STAGE=$(STAGE) ./scripts/publish-images.sh

# Registry Publishing (version-aware upsert with locking and backup)
# This is the safe default that:
#   1. Acquires a lock to prevent concurrent writes
#   2. Backs up the current remote state
#   3. Downloads and merges with version-aware logic
#   4. Pushes, verifies, and releases lock
#   5. On failure: restores backup, keeps lock for investigation
#
# Usage:
#   make publish-registry                                        # Safe upsert to dev
#   make publish-registry STAGE=prod                             # Safe upsert to production
#   make publish-registry DRY_RUN=1                              # Show what would happen
#   make publish-registry STAGE=dev TYPE=app|service NAME=foo FORCE=1    # Force specific extension (dev only)
#
# FORCE flag restrictions:
#   - Only allowed for STAGE=dev
#   - Requires TYPE and NAME to specify which extension to force
#   - Bypasses version checks only for the specified extension
#
# Note: This target automatically rebuilds the registry for the target STAGE
# to ensure image tags match the deployment stage (e.g., no -dev tags in prod).

.PHONY: publish-registry
publish-registry: ## Publish registry with version-aware upsert - usage: make publish-registry [STAGE=dev|stage|prod] [TYPE=app|service|tool NAME=name FORCE=1] [DRY_RUN=1]
	@if [ "$(FORCE)" = "1" ]; then \
		if [ "$(STAGE)" != "dev" ]; then \
			echo "Error: FORCE is only allowed for STAGE=dev (got STAGE=$(STAGE))"; \
			echo "For stage/prod, you must bump the version in kamiwaza.json"; \
			exit 1; \
		fi; \
		if [ -z "$(TYPE)" ] || [ -z "$(NAME)" ]; then \
			echo "Error: FORCE requires TYPE and NAME to specify which extension to force"; \
			echo "Usage: make publish-registry STAGE=dev TYPE=app|service NAME=my-app FORCE=1"; \
			exit 1; \
		fi; \
	fi
	@echo "Building registry for stage: $(STAGE)"
	@$(REQUIREMENTS_PYTHON) scripts/build-registry.py --stage $(STAGE) --repo-version $(REPO_VERSION)
	@ARGS="--stage $(STAGE) --repo-version $(REPO_VERSION)"; \
	if [ "$(DRY_RUN)" = "1" ]; then ARGS="$$ARGS --dry-run"; fi; \
	if [ "$(FORCE)" = "1" ]; then \
		FORCE_NAME=$$($(SCRIPT_PYTHON) -c "import json; print(json.load(open('$(TYPE)s/$(NAME)/kamiwaza.json'))['name'])"); \
		ARGS="$$ARGS --force-name $$FORCE_NAME"; \
	fi; \
	$(REQUIREMENTS_PYTHON) scripts/registry-upsert.py $$ARGS

.PHONY: publish-registry-dry-run
publish-registry-dry-run: ## Show what registry upsert would do (dry run)
	@echo "Building registry for stage: $(STAGE)"
	@$(REQUIREMENTS_PYTHON) scripts/build-registry.py --stage $(STAGE) --repo-version $(REPO_VERSION)
	@$(REQUIREMENTS_PYTHON) scripts/registry-upsert.py --stage $(STAGE) --repo-version $(REPO_VERSION) --dry-run

.PHONY: publish-registry-force
publish-registry-force: ## Force publish specific extension (dev only) - usage: make publish-registry-force TYPE=app|service NAME=name
	@if [ "$(STAGE)" != "dev" ]; then \
		echo "Error: Force publish is only allowed for STAGE=dev"; \
		exit 1; \
	fi
	@if [ -z "$(TYPE)" ] || [ -z "$(NAME)" ]; then \
		echo "Error: TYPE and NAME are required for force publish"; \
		echo "Usage: make publish-registry-force TYPE=app|service NAME=my-app"; \
		exit 1; \
	fi
	@echo "Building registry for stage: $(STAGE)"
	@$(REQUIREMENTS_PYTHON) scripts/build-registry.py --stage $(STAGE) --repo-version $(REPO_VERSION)
	@FORCE_NAME=$$($(SCRIPT_PYTHON) -c "import json; print(json.load(open('$(TYPE)s/$(NAME)/kamiwaza.json'))['name'])"); \
	$(REQUIREMENTS_PYTHON) scripts/registry-upsert.py --stage $(STAGE) --repo-version $(REPO_VERSION) --force-name "$$FORCE_NAME"

# Remove extension from published registry by name
# Searches both apps.json and tools.json - no TYPE required.
# NAME is the registry entry name (as shown in `make list-published`), not a directory name.
#
# Usage:
#   make unpublish NAME="Kaizen v3"                    # Remove from dev (default)
#   make unpublish NAME="Kaizen v3" STAGE=prod         # Remove from production
#   make unpublish NAME="Kaizen v3" DRY_RUN=1          # Show what would be removed
.PHONY: unpublish
unpublish: ## Remove extension from registry by name - usage: make unpublish NAME="Extension Name" [STAGE=dev|stage|prod] [DRY_RUN=1]
	@if [ -z "$(NAME)" ]; then \
		echo "Error: NAME is required (registry entry name from 'make list-published')"; \
		echo "Usage: make unpublish NAME=\"Extension Name\" [STAGE=dev|stage|prod] [DRY_RUN=1]"; \
		exit 1; \
	fi
	@DRY_RUN_FLAG=""; \
	if [ "$(DRY_RUN)" = "1" ]; then DRY_RUN_FLAG="--dry-run"; fi; \
	$(REQUIREMENTS_PYTHON) scripts/registry-remove.py --stage $(STAGE) --repo-version $(REPO_VERSION) --name "$(NAME)" $$DRY_RUN_FLAG

# Remove registry lock (scoped to garden dir)
.PHONY: remove-publish-lock
remove-publish-lock: ## Remove registry publish lock - usage: make remove-publish-lock [STAGE=dev|stage|prod]
	@$(REQUIREMENTS_PYTHON) scripts/lib/s3_operations.py --stage $(STAGE) --garden-dir $(GARDEN_DIR_NAME) --release-lock

# Download current registry state
.PHONY: download-registry
download-registry: ## Download current remote registry for inspection - usage: make download-registry [STAGE=dev|stage|prod]
	@$(REQUIREMENTS_PYTHON) -c "from scripts.lib.s3_operations import download_registry, get_bucket_for_stage; \
		import os; \
		from pathlib import Path; \
		stage = '$(STAGE)'; \
		repo_version = '$(REPO_VERSION)'; \
		garden_dir = 'default' if repo_version == '1' else f'v{repo_version}'; \
		bucket = get_bucket_for_stage(stage); \
		local_path = Path('build/registry-download'); \
		print(f'Downloading registry from {bucket}/garden/{garden_dir}/...'); \
		working_path, _ = download_registry(bucket, garden_dir, local_path, create_backup=False); \
		print(f'Downloaded to: {working_path}')"

.PHONY: publish-dry-run
publish-dry-run: ## Show what would be published (dry run for both registry and images)
	@echo "=== Registry Publish (dry run) ==="
	@$(REQUIREMENTS_PYTHON) scripts/registry-upsert.py --stage $(STAGE) --repo-version $(REPO_VERSION) --dry-run
	@echo ""
	@echo "=== Docker Images Publish (dry run) ==="
	@STAGE=$(STAGE) ./scripts/publish-images.sh --dry-run

# ==============================================================================
# CI/CD Helpers
# ==============================================================================

.PHONY: ci-validate
ci-validate: validate ## Run all validations for CI

.PHONY: ci-build
ci-build: validate build-registry ## Build registry for CI

.PHONY: ci-test
ci-test: test-all test-integration ## Run all tests for CI

endif # _BUILD_MK_
