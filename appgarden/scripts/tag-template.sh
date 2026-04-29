#!/bin/bash
#
# Bump version and create/push a git tag for the template repository
#
# Usage: ./scripts/tag-template.sh <PATCH|MINOR|MAJOR> [--dry-run]
#
# This script:
# 1. Gets the latest git tag (defaults to 0.0.0 if none)
# 2. Bumps the version based on the specified level
# 3. Creates and pushes the new tag
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

usage() {
    echo "Usage: $0 <PATCH|MINOR|MAJOR> [--dry-run] [--no-push]"
    echo ""
    echo "Bump version and create a git tag for the template repository."
    echo ""
    echo "Arguments:"
    echo "  PATCH|MINOR|MAJOR    Version bump level"
    echo ""
    echo "Options:"
    echo "  --dry-run            Show what would happen without making changes"
    echo "  --no-push            Create tag locally but don't push"
    echo "  -h, --help           Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 PATCH             # 0.1.1 -> 0.1.2"
    echo "  $0 MINOR             # 0.1.1 -> 0.2.0"
    echo "  $0 MAJOR             # 0.1.1 -> 1.0.0"
    echo "  $0 PATCH --dry-run   # Show what would happen"
    exit 0
}

# Parse arguments
LEVEL=""
DRY_RUN=false
NO_PUSH=false

while [[ $# -gt 0 ]]; do
    case $1 in
        PATCH|patch|MINOR|minor|MAJOR|major)
            LEVEL=$(echo "$1" | tr '[:lower:]' '[:upper:]')
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --no-push)
            NO_PUSH=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo -e "${RED}Error: Unknown argument: $1${NC}"
            usage
            ;;
    esac
done

if [[ -z "$LEVEL" ]]; then
    echo -e "${RED}Error: Version level required (PATCH, MINOR, or MAJOR)${NC}"
    usage
fi

# Get current version from latest tag
get_latest_version() {
    local latest
    latest=$(git tag --list --sort=-v:refname 2>/dev/null | head -1)
    if [[ -z "$latest" ]]; then
        echo "0.0.0"
    else
        echo "$latest"
    fi
}

# Bump version based on level
bump_version() {
    local version=$1
    local level=$2

    # Parse version parts
    local major minor patch
    IFS='.' read -r major minor patch <<< "$version"

    # Default to 0 if parsing fails
    major=${major:-0}
    minor=${minor:-0}
    patch=${patch:-0}

    case $level in
        PATCH)
            patch=$((patch + 1))
            ;;
        MINOR)
            minor=$((minor + 1))
            patch=0
            ;;
        MAJOR)
            major=$((major + 1))
            minor=0
            patch=0
            ;;
    esac

    echo "${major}.${minor}.${patch}"
}

# Main execution
cd "$REPO_ROOT"

echo -e "${BLUE}=== Template Version Tagging ===${NC}"
echo ""

# Check for uncommitted changes
if [[ -n $(git status --porcelain) ]]; then
    echo -e "${YELLOW}Warning: You have uncommitted changes${NC}"
    git status --short
    echo ""
    if [[ "$DRY_RUN" == "false" ]]; then
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            exit 1
        fi
    fi
fi

# Get current and new versions
CURRENT_VERSION=$(get_latest_version)
NEW_VERSION=$(bump_version "$CURRENT_VERSION" "$LEVEL")

echo "Current version: ${BOLD}${CURRENT_VERSION}${NC}"
echo "New version:     ${BOLD}${GREEN}${NEW_VERSION}${NC}"
echo "Bump level:      ${LEVEL}"
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "${YELLOW}[DRY RUN] Would execute:${NC}"
    echo "  git tag ${NEW_VERSION}"
    if [[ "$NO_PUSH" == "false" ]]; then
        echo "  git push origin ${NEW_VERSION}"
    fi
    echo ""
    echo -e "${YELLOW}No changes made.${NC}"
    exit 0
fi

# Create tag
echo -e "${BLUE}Creating tag ${NEW_VERSION}...${NC}"
git tag "$NEW_VERSION"
echo -e "${GREEN}Tag created: ${NEW_VERSION}${NC}"

# Push tag
if [[ "$NO_PUSH" == "false" ]]; then
    echo -e "${BLUE}Pushing tag to origin...${NC}"
    git push origin "$NEW_VERSION"
    echo -e "${GREEN}Tag pushed: ${NEW_VERSION}${NC}"
else
    echo -e "${YELLOW}Skipping push (--no-push specified)${NC}"
    echo "To push later: git push origin ${NEW_VERSION}"
fi

echo ""
echo -e "${GREEN}=== Done ===${NC}"
echo "Template tagged as ${BOLD}${NEW_VERSION}${NC}"
