# help.mk - Help system for Kamiwaza Extensions Makefiles
#
# This file provides the main help target and coordinates
# category-specific help from other modules

ifndef _HELP_MK_
_HELP_MK_ := 1

# ==============================================================================
# Main Help Target
# ==============================================================================

.PHONY: help
help: ## Show this help message
	@$(call print_header,Kamiwaza Extensions Management)
	@echo ""
	@echo "Usage:"
	@echo "  make [target] [VARIABLE=value ...]"
	@echo ""
	@echo "$(BOLD)Quick Start:$(RESET)"
	@echo "  make list                                                   $(COMMENT)# List all extensions$(RESET)"
	@echo "  make build $(ARGS)TYPE=app NAME=kaizen-app$(RESET)                    $(COMMENT)# Build specific app$(RESET)"
	@echo "  make build $(ARGS)TYPE=service NAME=service-milvus$(RESET)            $(COMMENT)# Build specific service$(RESET)"
	@echo "  make test $(ARGS)TYPE=tool NAME=websearch-tool$(RESET)               $(COMMENT)# Test specific tool$(RESET)"
	@echo "  make validate                                               $(COMMENT)# Validate all extensions$(RESET)"
	@echo "  make validate $(ARGS)TYPE=app NAME=kaizen-app$(RESET)                 $(COMMENT)# Validate specific extension$(RESET)"
	@echo ""
	@$(call print_section,Extension Discovery)
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' make/discovery.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(SCRIPT_PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Build and Test)
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' make/build.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(SCRIPT_PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Metadata and Registry)
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' make/metadata.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(SCRIPT_PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Template Management)
	@echo "$(YELLOW)Note: These commands require a running Kamiwaza deployment$(RESET)"
	@echo "$(DIM)Environment: KAMIWAZA_API_URL=$(KAMIWAZA_API_URL)$(RESET)"
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' make/templates.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(SCRIPT_PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Development Workflow)
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' make/dev.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(SCRIPT_PYTHON) scripts/format-help.py
	@echo ""
	@$(call print_section,Category Help)
	@echo "For focused help on specific categories:"
	@echo "  make help-discovery                                         $(COMMENT)# Extension discovery commands$(RESET)"
	@echo "  make help-build                                             $(COMMENT)# Building and testing commands$(RESET)"
	@echo "  make help-metadata                                          $(COMMENT)# Metadata management commands$(RESET)"
	@echo "  make help-templates                                         $(COMMENT)# Template management commands$(RESET)"
	@echo "  make help-dev                                               $(COMMENT)# Development workflow commands$(RESET)"
	@echo "  make help-examples                                          $(COMMENT)# Example commands$(RESET)"

# ==============================================================================
# Category-Specific Help Targets
# ==============================================================================

.PHONY: help-discovery
help-discovery: ## Show extension discovery commands
	@$(call print_header,Extension Discovery Commands)
	@echo ""
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' make/discovery.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(SCRIPT_PYTHON) scripts/format-help.py

.PHONY: help-build
help-build: ## Show building and testing commands
	@$(call print_header,Building and Testing Commands)
	@echo ""
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' make/build.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(SCRIPT_PYTHON) scripts/format-help.py

.PHONY: help-metadata
help-metadata: ## Show metadata management commands
	@$(call print_header,Metadata Management Commands)
	@echo ""
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' make/metadata.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(SCRIPT_PYTHON) scripts/format-help.py

.PHONY: help-templates
help-templates: ## Show template management commands
	@$(call print_header,Template Management Commands)
	@echo ""
	@echo "$(YELLOW)Note: These commands require a running Kamiwaza deployment$(RESET)"
	@echo "$(DIM)Environment: KAMIWAZA_API_URL=$(KAMIWAZA_API_URL)$(RESET)"
	@echo ""
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' make/templates.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(SCRIPT_PYTHON) scripts/format-help.py

.PHONY: help-dev
help-dev: ## Show development workflow commands
	@$(call print_header,Development Workflow Commands)
	@echo ""
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' make/dev.mk | \
		sed 's/:.*##/##/' | \
		sort | \
		$(SCRIPT_PYTHON) scripts/format-help.py

.PHONY: help-examples
help-examples: ## Show example commands
	@$(call print_header,Example Commands)
	@echo ""
	@echo "$(BOLD)Creating Extensions:$(RESET)"
	@echo "  make new TYPE=app NAME=my-app         # Create app with source"
	@echo "  make new TYPE=service NAME=service-milvus  # Create service with source"
	@echo "  make new TYPE=tool NAME=my-tool       # Create tool with source"
	@echo "  make new-external TYPE=app NAME=ext   # Create external app"
	@echo ""
	@echo "$(BOLD)Building & Testing:$(RESET)"
	@echo "  make build TYPE=app NAME=kaizen-app   # Build specific app"
	@echo "  make build TYPE=service NAME=service-milvus  # Build specific service"
	@echo "  make test TYPE=tool NAME=search-tool  # Test specific tool"
	@echo "  make build-all                        # Build all extensions"
	@echo ""
	@echo "$(BOLD)Validation & Registry:$(RESET)"
	@echo "  make validate                         # Validate all metadata"
	@echo "  make generate-appgarden-compose TYPE=app NAME=my-app  # Generate App Garden compose"
	@echo "  make generate-appgarden-compose TYPE=service NAME=service-milvus  # Generate App Garden compose"
	@echo "  make build-registry                   # Generate registry files"
	@echo ""
	@echo "$(BOLD)Publishing:$(RESET)"
	@echo "  make publish-registry                 # Safe upsert with locking/backup"
	@echo "  make publish-registry DRY_RUN=1       # Show what upsert would do"
	@echo "  make publish-registry FORCE=1         # Force push (bypass version checks)"
	@echo "  make remove-publish-lock              # Remove registry publish lock"
	@echo "  make download-registry                # Download current remote registry"
	@echo "  make publish-registry-direct          # Legacy direct S3 sync (no checks)"
	@echo ""
	@echo "$(BOLD)Templates (requires running Kamiwaza):$(RESET)"
	@echo "  make templates-list                   # List available templates"
	@echo "  make garden-push TYPE=app NAME=my-app [TEMPLATE_ID=uuid]        # Push/Update app template"
	@echo "  make garden-list [FORMAT=json]                # List installed templates"
	@echo "  make garden-sync NAMES=\"app-a app-b\"        # Sync templates from Garden (optional list)"
	@echo "  make demo                                      # Run end-to-end demo (ai-chatbot-app)"
	@echo "  make templates-inspect TYPE=tool NAME=search  # Inspect template details"

endif # _HELP_MK_
