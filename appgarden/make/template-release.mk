# template-release.mk - Release targets for the template repository itself
#
# This file is EXCLUDED from copier and should NOT be copied to downstream repos.
# These targets are only used in the upstream kamiwaza-extensions-template repo.

ifndef _TEMPLATE_RELEASE_MK_
_TEMPLATE_RELEASE_MK_ := 1

# ==============================================================================
# Template Repository Versioning
# ==============================================================================

# Tag the template repository (not extensions)
# Usage:
#   make tag-template LEVEL=PATCH           # 0.1.1 -> 0.1.2
#   make tag-template LEVEL=MINOR           # 0.1.1 -> 0.2.0
#   make tag-template LEVEL=MAJOR           # 0.1.1 -> 1.0.0
#   make tag-template LEVEL=PATCH DRY_RUN=1 # Show what would happen
#   make tag-template LEVEL=PATCH NO_PUSH=1 # Create tag but don't push
.PHONY: tag-template
tag-template: ## Tag template repo - usage: make tag-template LEVEL=PATCH|MINOR|MAJOR [DRY_RUN=1] [NO_PUSH=1]
	@if [ -z "$(LEVEL)" ]; then \
		echo "Error: LEVEL is required (PATCH, MINOR, or MAJOR)"; \
		echo "Usage: make tag-template LEVEL=PATCH|MINOR|MAJOR"; \
		exit 1; \
	fi; \
	ARGS="$(LEVEL)"; \
	if [ "$(DRY_RUN)" = "1" ]; then ARGS="$$ARGS --dry-run"; fi; \
	if [ "$(NO_PUSH)" = "1" ]; then ARGS="$$ARGS --no-push"; fi; \
	./scripts/tag-template.sh $$ARGS

endif # _TEMPLATE_RELEASE_MK_
