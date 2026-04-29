# dev.mk - Development workflow commands
#
# Commands for creating and managing extensions during development

ifndef _DEV_MK_
_DEV_MK_ := 1

# ==============================================================================
# Development Workflow
# ==============================================================================

.PHONY: new
new: new-internal ## Create new extension with source (alias for new-internal)

.PHONY: new-internal
new-internal: ## Create new extension with source - usage: make new-internal TYPE=app|service|tool NAME=my-app
	$(call print_section,Creating new internal $(TYPE): $(NAME))
	@mkdir -p $(TYPE)s/$(NAME)
	@echo "# $(NAME)" > $(TYPE)s/$(NAME)/README.md
	@echo "Created $(TYPE)s/$(NAME)/"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Add kamiwaza.json"
	@echo "  2. Add source code"
	@echo "  3. Add Dockerfile(s)"
	@echo "  4. Add docker-compose.yml"
	@echo "  5. Run 'make generate-appgarden-compose TYPE=$(TYPE) NAME=$(NAME)'"
	@echo "  6. Run 'make validate'"

.PHONY: new-external
new-external: ## Create new extension for external images - usage: make new-external TYPE=app|service|tool NAME=my-app
	$(call print_section,Creating new external $(TYPE): $(NAME))
	@mkdir -p $(TYPE)s/$(NAME)
	@echo "# $(NAME)" > $(TYPE)s/$(NAME)/README.md
	@echo "# External Extension" >> $(TYPE)s/$(NAME)/README.md
	@echo "" >> $(TYPE)s/$(NAME)/README.md
	@echo "This extension references external Docker images." >> $(TYPE)s/$(NAME)/README.md
	@echo "" >> $(TYPE)s/$(NAME)/README.md
	@echo "## Source Code" >> $(TYPE)s/$(NAME)/README.md
	@echo "Source code is maintained at: [URL]" >> $(TYPE)s/$(NAME)/README.md
	@echo "Created $(TYPE)s/$(NAME)/"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Add kamiwaza.json (with 'image' field for tools)"
	@echo "  2. Add docker-compose.appgarden.yml (for apps/services) or Dockerfile reference (for tools)"
	@echo "  3. Update README.md with source repository URL"
	@echo "  4. Run 'make validate'"

.PHONY: new-hybrid
new-hybrid: ## Create new extension with git submodule - usage: make new-hybrid TYPE=app|service|tool NAME=my-app REPO=https://github.com/user/repo.git
	$(call print_section,Creating new hybrid $(TYPE): $(NAME))
	@mkdir -p $(TYPE)s/$(NAME)
	@echo "# $(NAME)" > $(TYPE)s/$(NAME)/README.md
	@echo "# Hybrid Extension (Git Submodule)" >> $(TYPE)s/$(NAME)/README.md
	@echo "" >> $(TYPE)s/$(NAME)/README.md
	@echo "This extension uses a git submodule for source code." >> $(TYPE)s/$(NAME)/README.md
	@if [ -n "$(REPO)" ]; then \
		cd $(TYPE)s/$(NAME) && git submodule add $(REPO) src; \
		echo "Added submodule from $(REPO)"; \
	else \
		echo "Note: Add submodule with: cd $(TYPE)s/$(NAME) && git submodule add [REPO_URL] src"; \
	fi
	@echo "Created $(TYPE)s/$(NAME)/"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Add kamiwaza.json"
	@echo "  2. Add Dockerfile(s) that reference src/ directory"
	@echo "  3. Add docker-compose.yml"
	@echo "  4. Run 'make generate-appgarden-compose TYPE=$(TYPE) NAME=$(NAME)'"
	@echo "  5. Run 'make validate'"

# ==============================================================================
# Quick Development Shortcuts
# ==============================================================================

.PHONY: dev
dev: ## Quick dev test - usage: make dev TYPE=app NAME=kaizen-app
	@if [ -z "$(TYPE)" ] || [ -z "$(NAME)" ]; then \
		$(call print_error,Usage: make dev TYPE=app NAME=kaizen-app); \
		exit 1; \
	fi
	$(call print_section,Running $(TYPE)/$(NAME) locally)
	@cd $(TYPE)s/$(NAME) && docker-compose up --build

.PHONY: dev-rebuild
dev-rebuild: ## Rebuild and run - usage: make dev-rebuild TYPE=app NAME=kaizen-app
	@if [ -z "$(TYPE)" ] || [ -z "$(NAME)" ]; then \
		$(call print_error,Usage: make dev-rebuild TYPE=app NAME=kaizen-app); \
		exit 1; \
	fi
	$(call print_section,Rebuilding $(TYPE)/$(NAME))
	@cd $(TYPE)s/$(NAME) && docker-compose build --no-cache && docker-compose up

.PHONY: logs
logs: ## Show logs - usage: make logs TYPE=app NAME=kaizen-app
	@if [ -z "$(TYPE)" ] || [ -z "$(NAME)" ]; then \
		$(call print_error,Usage: make logs TYPE=app NAME=kaizen-app); \
		exit 1; \
	fi
	@cd $(TYPE)s/$(NAME) && docker-compose logs -f

.PHONY: shell
shell: ## Open shell in container - usage: make shell TYPE=app NAME=kaizen-app SERVICE=backend
	@if [ -z "$(TYPE)" ] || [ -z "$(NAME)" ]; then \
		$(call print_error,Usage: make shell TYPE=app NAME=kaizen-app SERVICE=backend); \
		exit 1; \
	fi
	@cd $(TYPE)s/$(NAME) && docker-compose exec $(SERVICE) /bin/sh

# ==============================================================================
# Documentation
# ==============================================================================

.PHONY: docs
docs: ## Show documentation locations
	$(call print_header,📚 Documentation)
	@echo ""
	@echo "Main documentation:"
	@echo "  - docs/developer-guide.md"
	@echo "  - docs/planning/"
	@echo ""
	@echo "AI assistant integration:"
	@echo "  - CLAUDE.md (repository overview)"
	@echo "  - .ai/README.md (AI integration guide)"
	@echo "  - .ai/rules/ (development standards)"
	@echo "  - .ai/prompts/ (task templates)"
	@echo ""
	@echo "Quick references:"
	@echo "  - README.md (getting started)"
	@echo "  - Makefile help: make help"

endif # _DEV_MK_
