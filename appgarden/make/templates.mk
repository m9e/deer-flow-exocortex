# templates.mk - Template management commands
#
# Commands for managing templates with Kamiwaza deployment
# Requires running Kamiwaza (default: KAMIWAZA_API_URL)

ifndef _TEMPLATES_MK_
_TEMPLATES_MK_ := 1

# ==============================================================================
# Template Management (requires running Kamiwaza)
# ==============================================================================

# Listing templates (read from Kamiwaza)
.PHONY: templates-list
templates-list: ## List all available templates from Kamiwaza
	$(call print_section,Listing all templates from Kamiwaza)
	@$(SCRIPT_PYTHON) scripts/manage-templates.py list all

.PHONY: templates-list-apps
templates-list-apps: ## List available app templates from Kamiwaza
	@$(SCRIPT_PYTHON) scripts/manage-templates.py list apps

.PHONY: templates-list-tools
templates-list-tools: ## List available tool templates from Kamiwaza
	@$(SCRIPT_PYTHON) scripts/manage-templates.py list tools

.PHONY: templates-list-services
templates-list-services: ## List available service templates from Kamiwaza
	@$(SCRIPT_PYTHON) scripts/manage-templates.py list services

.PHONY: templates-list-deployments
templates-list-deployments: ## List current deployments from Kamiwaza
	@$(SCRIPT_PYTHON) scripts/manage-templates.py list deployments

# Pushing templates (push to Kamiwaza instance)
# Set KAMIWAZA_VERIFY_SSL=false for self-signed certificates
# Set KAMIWAZA_USERNAME and KAMIWAZA_PASSWORD for authentication
.PHONY: kamiwaza-push
KAMIWAZA_PUSH_CHECK_LOCAL_IMAGES ?= 1

kamiwaza-push: ## Push local app/service/tool template to Kamiwaza instance TYPE={app|service|tool} NAME={name}
ifndef TYPE
	$(error TYPE is required: make kamiwaza-push TYPE=app NAME=my-app)
endif
ifneq ($(filter $(TYPE),app service tool),$(TYPE))
	$(error TYPE must be 'app', 'service', or 'tool': make kamiwaza-push TYPE=app NAME=my-app)
endif
ifndef NAME
	$(error NAME is required: make kamiwaza-push TYPE=app NAME=my-app)
endif
ifeq ($(filter 1,$(KAMIWAZA_PUSH_CHECK_LOCAL_IMAGES)),1)
	@$(SCRIPT_PYTHON) scripts/check-local-extension-images.py \
		--type $(TYPE) --name $(NAME) --stage $(STAGE) --repo-version $(REPO_VERSION) --image-prefix $(IMAGE_PREFIX)
endif
	@$(MAKE) build-registry
	$(call print_section,Pushing $(TYPE) template '$(NAME)' to Kamiwaza)
	@KAMIWAZA_VERIFY_SSL=false $(SCRIPT_PYTHON) scripts/manage-templates.py \
		$(if $(strip $(KAMIWAZA_USERNAME)),--username $(KAMIWAZA_USERNAME),) \
		$(if $(strip $(KAMIWAZA_PASSWORD)),--password $(KAMIWAZA_PASSWORD),) \
		--repo-version $(REPO_VERSION) \
		garden-push $(TYPE) $(NAME) $(if $(strip $(TEMPLATE_ID)),--template-id $(TEMPLATE_ID),)
ifneq ($(filter 3,$(REPO_VERSION)),)
	@CLUSTER="$(or $(KIND_CLUSTER_NAME),kamiwaza-dev)"; \
	DETECTED_CONTEXT=""; \
	CLUSTER_FOUND="false"; \
	if command -v kind >/dev/null 2>&1; then \
		CLUSTERS=$$(kind get clusters 2>/dev/null || true); \
		if echo "$$CLUSTERS" | grep -qxF "$$CLUSTER"; then \
			CLUSTER_FOUND="true"; \
			DETECTED_CONTEXT="$${DOCKER_CONTEXT:-}"; \
		elif DOCKER_HOST= DOCKER_CONTEXT=podman kind get clusters 2>/dev/null | grep -qxF "$$CLUSTER"; then \
			CLUSTER_FOUND="true"; \
			DETECTED_CONTEXT="podman"; \
		fi; \
	fi; \
	if [ "$$CLUSTER_FOUND" = "true" ]; then \
		echo ""; \
		echo "Loading images into Kind cluster..."; \
		if [ -n "$$DETECTED_CONTEXT" ]; then \
			DOCKER_CONTEXT="$$DETECTED_CONTEXT" ./scripts/kind-load-images.sh \
				--repo-version $(REPO_VERSION) --cluster "$$CLUSTER"; \
		else \
			./scripts/kind-load-images.sh \
				--repo-version $(REPO_VERSION) --cluster "$$CLUSTER"; \
		fi; \
	else \
		echo ""; \
		echo "$(YELLOW)No Kind cluster found — skipping image loading into containerd$(NC)"; \
		echo "Run 'make kind-load-images' manually after cluster is available."; \
	fi
endif

# Load images into Kind cluster's containerd (for v3/K8s extensions)
# KIND_CLUSTER_NAME defaults to kamiwaza-dev
KIND_CLUSTER_NAME ?= kamiwaza-dev

.PHONY: kind-load-images
kind-load-images: ## Load exported Docker images into Kind cluster - usage: make kind-load-images [KIND_CLUSTER_NAME=name]
	@./scripts/kind-load-images.sh --repo-version $(REPO_VERSION) --cluster $(KIND_CLUSTER_NAME)

.PHONY: kind-load-images-dry-run
kind-load-images-dry-run: ## Show what images would be loaded into Kind (dry run)
	@./scripts/kind-load-images.sh --repo-version $(REPO_VERSION) --cluster $(KIND_CLUSTER_NAME) --dry-run

.PHONY: kamiwaza-list
kamiwaza-list: ## List app templates on Kamiwaza instance
	$(call print_section,Listing Kamiwaza templates)
	@KAMIWAZA_VERIFY_SSL=false $(SCRIPT_PYTHON) scripts/manage-templates.py \
		$(if $(strip $(KAMIWAZA_USERNAME)),--username $(KAMIWAZA_USERNAME),) \
		$(if $(strip $(KAMIWAZA_PASSWORD)),--password $(KAMIWAZA_PASSWORD),) \
		--repo-version $(REPO_VERSION) \
		garden-list $(if $(FORMAT),--format $(FORMAT),)

# Inspecting templates
.PHONY: templates-inspect
templates-inspect: ## Inspect template details from Kamiwaza TYPE={app|service|tool} NAME={name}
ifndef TYPE
	$(error TYPE is required: make templates-inspect TYPE=app NAME=my-app)
endif
ifndef NAME
	$(error NAME is required: make templates-inspect TYPE=app NAME=my-app)
endif
	$(call print_section,Inspecting $(TYPE) template '$(NAME)')
	@$(SCRIPT_PYTHON) scripts/manage-templates.py inspect $(TYPE) $(NAME)

endif # _TEMPLATES_MK_
