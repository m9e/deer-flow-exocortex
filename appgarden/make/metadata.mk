# metadata.mk - Metadata and validation commands
#
# Commands for managing and validating extension metadata

ifndef _METADATA_MK_
_METADATA_MK_ := 1

# Deployment stage (precedence: STAGE param > env > default dev)
# - dev: Image tags get -dev suffix ($(IMAGE_PREFIX)/app:1.0.0-dev)
# - stage: Image tags get -stage suffix ($(IMAGE_PREFIX)/app:1.0.0-stage)
# - prod: No suffix ($(IMAGE_PREFIX)/app:1.0.0)
STAGE ?= dev

# Repository format version (precedence: REPO_VERSION param/env > .repo-version file > default 2)
# - 2/3: Modern format with kamiwaza_version constraints, images/ folder → garden/v{N}/
# - 1: Legacy format without version constraints, app-garden-images/ folder → garden/default/
# Usage:
#   make build-registry                    # Uses 2 (default), dev stage
#   make build-registry STAGE=prod         # Uses 2, prod stage (no tag suffix)
#   make build-registry REPO_VERSION=3    # Uses garden/v3 (K8s extensions)
#   make build-registry REPO_VERSION=1    # Uses legacy garden/default
REPO_VERSION_FILE := $(strip $(shell cat .repo-version 2>/dev/null))
REPO_VERSION ?= $(or $(REPO_VERSION_FILE),2)
export REPO_VERSION
# Map REPO_VERSION to directory name: 1 → "default", everything else → "v{N}"
GARDEN_DIR_NAME := $(if $(filter 1,$(REPO_VERSION)),default,v$(REPO_VERSION))
REGISTRY_DIR := build/kamiwaza-extension-registry/garden/$(GARDEN_DIR_NAME)
# Image directory name: all non-1 use "images", 1 uses "app-garden-images"
IMAGES_DIR_NAME := $(if $(filter 1,$(REPO_VERSION)),app-garden-images,images)

# ==============================================================================
# Metadata Management
# ==============================================================================

.PHONY: validate
validate: ## Validate extension(s) - usage: make validate [TYPE={app|service|tool} NAME={name}]
ifdef TYPE
ifndef NAME
	$(error NAME is required when TYPE is specified: make validate TYPE=app|service|tool NAME=my-app)
endif
	$(call print_section,Validating $(TYPE)/$(NAME))
	@$(REQUIREMENTS_PYTHON) scripts/validate-metadata.py --type $(TYPE) --name $(NAME)
	@echo ""
	@$(REQUIREMENTS_PYTHON) scripts/validate-compose.py --type $(TYPE) --name $(NAME)
else
	$(call print_section,Validating all extension metadata)
	@$(REQUIREMENTS_PYTHON) scripts/validate-metadata.py
	@echo ""
	$(call print_section,Validating all docker-compose files)
	@$(REQUIREMENTS_PYTHON) scripts/validate-compose.py
endif

.PHONY: sync-compose
sync-compose: ## Sync compose files for all extensions
	@$(REQUIREMENTS_PYTHON) scripts/sync-compose.py --all

.PHONY: generate-appgarden-compose
generate-appgarden-compose: ## Generate App Garden compose file for specific extension TYPE={app|service|tool} NAME={name}
	@$(REQUIREMENTS_PYTHON) scripts/sync-compose.py --type $(TYPE) --name $(NAME)

.PHONY: check-compose
check-compose: ## Check if compose files need syncing
	@$(REQUIREMENTS_PYTHON) scripts/sync-compose.py --all --check

# Default to exporting images unless explicitly disabled
EXPORT_IMAGES ?= true
REGISTRY_ROOT := build/kamiwaza-extension-registry

.PHONY: build-registry
build-registry: ## Generate registry and export images (disable with EXPORT_IMAGES=false)
	@$(REQUIREMENTS_PYTHON) scripts/build-registry.py --stage $(STAGE) --repo-version $(REPO_VERSION)
	@echo ""
	$(call print_success,Registry files generated in $(REGISTRY_ROOT)/garden/$(GARDEN_DIR_NAME)/)
ifeq ($(EXPORT_IMAGES),true)
	@echo ""
	$(call print_section,Exporting Docker images for offline use)
	@$(REQUIREMENTS_PYTHON) scripts/export-images.py --non-interactive --repo-version $(REPO_VERSION)
else
	@echo ""
	@echo "Skipping image export (EXPORT_IMAGES=false)"
endif

.PHONY: export-images
export-images: ## Export Docker images from registry for offline distribution
	$(call print_section,Exporting Docker images for offline use)
	@if [ ! -f $(REGISTRY_DIR)/apps.json ] || [ ! -f $(REGISTRY_DIR)/tools.json ]; then \
		echo "Registry files not found. Building registry first..."; \
		$(MAKE) build-registry; \
	fi
	@$(REQUIREMENTS_PYTHON) scripts/export-images.py --repo-version $(REPO_VERSION)

.PHONY: package-registry
package-registry: ## Package registry and images into a tar.gz file
	$(call print_section,Packaging registry for distribution)
	@if [ ! -d $(REGISTRY_ROOT) ] || [ ! -f $(REGISTRY_DIR)/apps.json ]; then \
		echo "Registry not found. Building registry first..."; \
		$(MAKE) build-registry; \
	fi
	@echo "Creating registry package..."
	@mkdir -p dist
	@TIMESTAMP=$$(date +"%Y%m%d-%H%M%S"); \
	PACKAGE_NAME="dist/kamiwaza-registry-$$TIMESTAMP.tar.gz"; \
	tar -czf "$$PACKAGE_NAME" -C build kamiwaza-extension-registry && \
	SIZE=$$(du -h "$$PACKAGE_NAME" | cut -f1) && \
	echo "" && \
	echo "[0;32m✓ Package created: $$PACKAGE_NAME ($$SIZE)[0m" && \
	echo "" && \
	echo "To extract and configure:" && \
	echo "  tar -xzf kamiwaza-registry-*.tar.gz" && \
	echo "  cd kamiwaza-extension-registry" && \
	echo "  ./package-setup.sh"

.PHONY: serve-registry
serve-registry: ## Serve registry files via HTTPS - usage: make serve-registry [PORT=58888]
	$(call print_section,Starting registry HTTPS server)
	@if [ ! -d $(REGISTRY_ROOT) ] || [ ! -f $(REGISTRY_DIR)/apps.json ]; then \
		echo "Registry not found. Building registry first..."; \
		$(MAKE) build-registry; \
	fi
	@echo ""
	@echo "Starting HTTPS server with self-signed certificate"
	@echo ""
	@cd $(REGISTRY_ROOT) && python3 serve-registry.py --port $(PORT)

.PHONY: verify-images
verify-images: ## Verify Docker images exist locally (default)
	@$(REQUIREMENTS_PYTHON) scripts/verify-images.py

.PHONY: verify-images-registry
verify-images-registry: ## Verify Docker images exist in registry
	@$(REQUIREMENTS_PYTHON) scripts/verify-images.py --registry --no-local

.PHONY: verify-images-all
verify-images-all: ## Verify Docker images exist locally and in registry
	@$(REQUIREMENTS_PYTHON) scripts/verify-images.py --local --registry

# Show specific registry entry
.PHONY: show-registry
show-registry: ## Show registry entry for app/service/tool - usage: make show-registry TYPE=app NAME=kaizen-app
	@if [ -z "$(TYPE)" ] || [ -z "$(NAME)" ]; then \
		echo "Usage: make show-registry TYPE=app|service|tool NAME=kaizen-app"; \
		exit 1; \
	fi
	@echo "Registry entry for $(TYPE): $(NAME)"
	@registry_file="$(REGISTRY_DIR)/$(TYPE)s.json"; \
	if [ "$(TYPE)" = "service" ]; then registry_file="$(REGISTRY_DIR)/apps.json"; fi; \
	cat $$registry_file 2>/dev/null | jq '.[] | select(.name=="$(NAME)")' | sed 's/^/  /' || echo "  Not found in registry"

endif # _METADATA_MK_
