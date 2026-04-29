# Kamiwaza Extensions Makefile
# Main entry point that includes all modular Makefiles

# Load .env if present (sets STAGE, AWS profiles, etc.)
-include .env

# Include all modules in correct order
# common.mk must be first as it defines shared variables
include make/common.mk
include make/discovery.mk
include make/build.mk
include make/quality.mk
include make/metadata.mk
include make/templates.mk
include make/dev.mk
include make/demo.mk
include make/help.mk

# Template-only targets (excluded from downstream repos via copier)
# Using -include so it doesn't error if file doesn't exist
-include make/template-release.mk

# Default target
.DEFAULT_GOAL := help
.PHONY: all
all: help

# Note: All actual targets are now defined in the included .mk files
# This main Makefile serves only as the entry point
