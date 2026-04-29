# quality.mk - Quality assurance and development workflow commands
#
# Commands for code quality, testing, and development setup

ifndef _QUALITY_MK_
_QUALITY_MK_ := 1

# ==============================================================================
# Development Setup
# ==============================================================================

.PHONY: install
install: ## Install dependencies and pre-commit hooks
	$(call print_section,Installing dependencies and pre-commit hooks)
	@echo "🚀 Creating virtual environment using uv"
	@uv sync
	@echo "🚀 Installing pre-commit hooks"
	@uv run pre-commit install
	@echo ""
	@echo "✓ Setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  - Run 'make check' to verify code quality"
	@echo "  - Run 'make test' to run all tests"
	@echo "  - See 'make help' for more commands"

# ==============================================================================
# Code Quality Checks
# ==============================================================================

.PHONY: check
check: ## Run all code quality checks
	$(call print_section,Running code quality checks)
	@echo "🚀 Checking lock file consistency with 'pyproject.toml'"
	@uv lock --check
	@echo ""
	@echo "🚀 Linting code: Running pre-commit"
	@uv run pre-commit run -a
	@echo ""
	@echo "🚀 Static type checking: Running mypy"
	@uv run mypy
	@echo ""
	@echo "🚀 Checking for obsolete dependencies: Running deptry"
	@uv run deptry .
	@echo ""
	@echo "✓ All quality checks passed!"

# ==============================================================================
# Cleanup
# ==============================================================================

.PHONY: clean
clean: ## Clean build artifacts and caches (keeps dependencies)
	$(call print_section,Cleaning build artifacts)
	@echo "Removing build artifacts..."
	@rm -rf build/
	@rm -rf *.egg-info
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name "*.pyo" -delete
	@find . -type f -name ".coverage" -delete
	@find . -type f -name "coverage.xml" -delete
	@echo "Cleanup complete!"

.PHONY: clean-deps
clean-deps: ## Clean all dependency caches (node_modules, .venv, etc.)
	$(call print_section,Cleaning dependency caches)
	@echo "Removing node_modules directories..."
	@find apps services tools -type d -name "node_modules" -exec rm -rf {} + 2>/dev/null || true
	@echo "Removing virtual environment..."
	@rm -rf .venv/
	@echo "Dependency cleanup complete!"

.PHONY: clean-all
clean-all: clean clean-deps ## Clean everything (build artifacts + dependencies)
	@echo "Full cleanup complete!"

.PHONY: distclean
distclean: clean-all ## Clean everything including distribution packages in dist/
	$(call print_section,Cleaning distribution artifacts)
	@echo "Removing distribution packages..."
	@rm -rf dist/
	@echo "Distribution cleanup complete!"

# ==============================================================================
# CI Pipeline
# ==============================================================================

.PHONY: ci-pipeline
ci-pipeline: ## Run full CI pipeline: build, test, sync-compose, validate, build-registry, package-registry
	$(call print_section,Running CI Pipeline)
	@echo "Step 1/6: Building all extensions"
	@$(MAKE) build-all || { echo "❌ Build failed"; exit 1; }
	@echo ""
	@echo "Step 2/6: Running tests"
	@$(MAKE) test-all || { echo "❌ Tests failed"; exit 1; }
	@echo ""
	@echo "Step 3/6: Syncing compose files"
	@$(MAKE) sync-compose || { echo "❌ Sync-compose failed"; exit 1; }
	@echo ""
	@echo "Step 4/6: Validating extensions"
	@$(MAKE) validate || { echo "❌ Validation failed"; exit 1; }
	@echo ""
	@echo "Step 5/6: Building registry"
	@$(MAKE) build-registry || { echo "❌ Build-registry failed"; exit 1; }
	@echo ""
	@echo "Step 6/6: Creating distribution package"
	@$(MAKE) package-registry || { echo "❌ Package-registry failed"; exit 1; }
	@echo ""
	$(call print_success,CI Pipeline completed successfully!)

endif # _QUALITY_MK_
