# common.mk - Shared variables and utilities for Kamiwaza Extensions
#
# This file contains:
# - Color definitions for terminal output
# - Common variables
# - Shared utility functions

ifndef _COMMON_MK_
_COMMON_MK_ := 1

# ==============================================================================
# Environment File Loading
# ==============================================================================

# Preserve AWS_PROFILE from the environment so it isn't overridden by .env
AWS_PROFILE_ENV := $(AWS_PROFILE)

# Load .env file if it exists (exports variables to environment)
# Note: We explicitly unexport guard variables to prevent submake issues
ifneq (,$(wildcard .env))
    include .env
    export
endif

# Unexport include guard variables so submakes can define their own targets
unexport _COMMON_MK_ _BUILD_MK_ _QUALITY_MK_ _DISCOVERY_MK_ _METADATA_MK_ _TEMPLATES_MK_ _DEV_MK_ _DEMO_MK_ _HELP_MK_

# Restore AWS_PROFILE from the environment if it was set at invocation
ifneq ($(strip $(AWS_PROFILE_ENV)),)
    AWS_PROFILE := $(AWS_PROFILE_ENV)
    export AWS_PROFILE
endif

# Docker image prefix (override in .env or environment)
# Default: repo-scoped GHCR namespace, e.g. ghcr.io/<github-org>/<repo-name>/images.
COMMON_MK_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ifeq ($(origin IMAGE_PREFIX), undefined)
ifneq ($(words $(abspath $(COMMON_MK_DIR)/..)),1)
$(error Repository paths containing spaces are not supported for IMAGE_PREFIX resolution; move the repo or set IMAGE_PREFIX explicitly)
endif
DEFAULT_IMAGE_PREFIX_SCRIPT := $(abspath $(COMMON_MK_DIR)/../scripts/default-image-prefix.sh)
DEFAULT_IMAGE_PREFIX_REPO := $(shell printf '%s' "$(notdir $(abspath $(COMMON_MK_DIR)/..))" | tr '[:upper:]' '[:lower:]' | tr ' _' '--')
DEFAULT_IMAGE_PREFIX_FALLBACK := ghcr.io/kamiwaza-internal/$(DEFAULT_IMAGE_PREFIX_REPO)/images
DEFAULT_IMAGE_PREFIX := $(shell "$(DEFAULT_IMAGE_PREFIX_SCRIPT)")
IMAGE_PREFIX := $(if $(strip $(DEFAULT_IMAGE_PREFIX)),$(DEFAULT_IMAGE_PREFIX),$(DEFAULT_IMAGE_PREFIX_FALLBACK))
endif
export IMAGE_PREFIX

# ==============================================================================
# Terminal Colors
# ==============================================================================

# Color definitions for pretty output
ifeq ($(OS),Windows_NT)
    # Windows doesn't support ANSI colors in cmd.exe
    RED :=
    GREEN :=
    YELLOW :=
    BLUE :=
    MAGENTA :=
    CYAN :=
    WHITE :=
    NC :=
    BOLD :=
    DIM :=
    RESET :=
    HEADER :=
    COMMAND :=
    ARGS :=
    COMMENT :=
else
    # ANSI color codes for Unix-like systems
    RED := \033[0;31m
    GREEN := \033[0;32m
    YELLOW := \033[0;33m
    BLUE := \033[0;34m
    MAGENTA := \033[0;35m
    CYAN := \033[0;36m
    WHITE := \033[0;37m
    NC := \033[0m  # No Color

    # Text formatting
    BOLD := \033[1m
    DIM := \033[2m
    RESET := \033[0m

    # Semantic colors for help output
    HEADER := \033[1;35m  # Bold magenta for headers
    COMMAND := \033[0m    # Default color for commands
    ARGS := \033[0;36m    # Cyan for arguments
    COMMENT := \033[2m    # Dim for comments
endif

# ==============================================================================
# Common Variables
# ==============================================================================

# Python environment
# Use virtual environment if it exists, otherwise fallback to python3
UV := $(shell command -v uv 2> /dev/null)
PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

# Default Python runner for lightweight helper scripts.
SCRIPT_PYTHON := $(PYTHON)

# Python runner for helper scripts that rely on scripts/requirements.txt.
# Prefer an existing repo virtualenv first. Otherwise, use uv for ephemeral
# dependency resolution so clean checkouts work on first run.
REQUIREMENTS_PYTHON := $(if $(wildcard .venv/bin/python),$(PYTHON),$(if $(UV),uv run --with-requirements scripts/requirements.txt python,$(PYTHON)))

# Kamiwaza connection defaults
KAMIWAZA_API_URL ?= https://localhost/api
KAMIWAZA_USERNAME ?= admin
KAMIWAZA_PASSWORD ?= kamiwaza

# Registry server defaults
PORT ?= 58888

# ==============================================================================
# Utility Functions
# ==============================================================================

# Check if a command exists
# Usage: $(call cmd_exists,command_name)
cmd_exists = $(shell command -v $(1) 2> /dev/null)

# Print a section header
# Usage: $(call print_header,Section Name)
define print_header
	@echo ""
	@echo "$(HEADER)==============================================================================$(RESET)"
	@echo "$(HEADER)$(1)$(RESET)"
	@echo "$(HEADER)==============================================================================$(RESET)"
	@echo ""
endef

# Print a subsection
# Usage: $(call print_section,Section Name)
define print_section
	@echo ""
	@echo "$(HEADER)$(1):$(RESET)"
endef

# Print success message
# Usage: $(call print_success,Message)
define print_success
	@echo "$(GREEN)✓ $(1)$(NC)"
endef

# Print error message
# Usage: $(call print_error,Message)
define print_error
	@echo "$(RED)✗ $(1)$(NC)"
endef

# Print warning message
# Usage: $(call print_warning,Message)
define print_warning
	@echo "$(YELLOW)⚠ $(1)$(NC)"
endef

endif # _COMMON_MK_
