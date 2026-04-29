# discovery.mk - Extension discovery commands
#
# Commands for listing and discovering extensions

ifndef _DISCOVERY_MK_
_DISCOVERY_MK_ := 1

# ==============================================================================
# Extension Discovery
# ==============================================================================

.PHONY: list
list: ## List all extensions
	@./scripts/discover-extensions.sh

.PHONY: list-apps
list-apps: ## List all apps
	@./scripts/discover-extensions.sh apps

.PHONY: list-tools
list-tools: ## List all tools
	@./scripts/discover-extensions.sh tools

.PHONY: list-services
list-services: ## List all services
	@./scripts/discover-extensions.sh services

# ==============================================================================
# Remote Registry Discovery
# ==============================================================================

.PHONY: list-published
list-published: ## List extensions published to remote registry - usage: make list-published [STAGE=dev|stage|prod]
	@$(REQUIREMENTS_PYTHON) scripts/list-published.py --stage $(STAGE) --repo-version $(REPO_VERSION)

endif # _DISCOVERY_MK_
