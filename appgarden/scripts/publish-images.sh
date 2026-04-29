#!/bin/bash
#
# Publish Docker images to registry
#
# By default, this script verifies images exist locally and pushes them.
# Use --build to build images before pushing.
#
# Stage-based tagging:
#   - dev:   version-dev tag
#   - stage: version-stage tag
#   - prod:  version tag (no suffix)
# Note: :latest is never pushed - prod should reference specific versions
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Default values
DRY_RUN=false
BUILD=false
REGISTRY=""
STAGE="${STAGE:-dev}"  # dev, stage, prod
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"  # Multi-arch platforms
FILTER_TYPE=""   # Filter to specific extension type (app, service, tool)
FILTER_NAME=""   # Filter to specific extension name
if [[ -n "${IMAGE_PREFIX:-}" ]]; then
    IMAGE_PREFIX="$(printf '%s' "${IMAGE_PREFIX%/}" | tr '[:upper:]' '[:lower:]')"
else
    IMAGE_PREFIX="$("${SCRIPT_DIR}/default-image-prefix.sh")"
fi

# Shared registry auth helpers
REGISTRY_AUTH_LIB="${SCRIPT_DIR}/lib/registry-auth.sh"
if [[ ! -f "${REGISTRY_AUTH_LIB}" ]]; then
    echo -e "${RED}Error: Missing registry auth library at ${REGISTRY_AUTH_LIB}${NC}"
    exit 1
fi
# shellcheck source=lib/registry-auth.sh
source "${REGISTRY_AUTH_LIB}"

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Publish Docker images for Kamiwaza extensions.

By default, verifies images exist locally and pushes them to the registry.
Use --build to build multi-arch images and push them directly.

Options:
  -d, --dry-run           Show what would be done without actually pushing
  -b, --build             Build multi-arch images and push (default: verify and push only)
  -r, --registry REG      Docker registry prefix (e.g., myorg/)
  -s, --stage STAGE       Deployment stage: dev, stage, prod (default: dev)
                          - dev:   version-dev tag
                          - stage: version-stage tag
                          - prod:  version tag (no suffix)
  -p, --platforms PLATS   Comma-separated platforms (default: linux/amd64,linux/arm64)
  -t, --type TYPE         Extension type filter: app, service, tool
  -n, --name NAME         Extension name filter (requires --type)
  -h, --help              Show this help message

Environment:
  STAGE                   Same as --stage option
  PLATFORMS               Same as --platforms option
  IMAGE_PREFIX            Defaults to ghcr.io/<github-org>/<repo-name>/images

Examples:
  # Verify and push images (default behavior, single-arch)
  $0

  # Dry run to see what would be pushed
  $0 --dry-run

  # Build and push multi-arch for dev stage
  $0 --build

  # Build and push multi-arch for production
  $0 --build --stage prod

  # Build for specific platforms only
  $0 --build --platforms linux/amd64

  # Push a specific extension
  $0 --type app --name my-app --stage prod

  # Push to custom registry for staging
  $0 --registry myorg/ --stage stage
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -b|--build)
            BUILD=true
            shift
            ;;
        -r|--registry)
            REGISTRY="$2"
            shift 2
            ;;
        -s|--stage)
            STAGE="$2"
            shift 2
            ;;
        -p|--platforms)
            PLATFORMS="$2"
            shift 2
            ;;
        -t|--type)
            FILTER_TYPE="$2"
            shift 2
            ;;
        -n|--name)
            FILTER_NAME="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            ;;
    esac
done

# Validate stage
case "$STAGE" in
    dev|stage|prod)
        ;;
    *)
        echo -e "${RED}Error: Invalid stage '$STAGE'. Must be: dev, stage, or prod${NC}"
        exit 1
        ;;
esac

# Validate filter args
if [[ -n "$FILTER_NAME" ]] && [[ -z "$FILTER_TYPE" ]]; then
    echo -e "${RED}Error: --name requires --type${NC}"
    exit 1
fi

if [[ -n "$FILTER_TYPE" ]]; then
    case "$FILTER_TYPE" in
        app|service|tool)
            ;;
        *)
            echo -e "${RED}Error: Invalid type '$FILTER_TYPE'. Must be: app, service, or tool${NC}"
            exit 1
            ;;
    esac
fi

# Function to get version from kamiwaza.json
get_version() {
    local ext_path=$1
    local metadata_file="$ext_path/kamiwaza.json"

    if [[ -f "$metadata_file" ]]; then
        python3 -c "
import json
data = json.load(open('$metadata_file'))
print(data.get('version', ''))
" 2>/dev/null || echo ""
    else
        echo ""
    fi
}

# Function to get image name from metadata
get_image_name() {
    local ext_path=$1
    local metadata_file="$ext_path/kamiwaza.json"

    if [[ ! -f "$metadata_file" ]]; then
        echo ""
        return
    fi

    # Try to get image name from metadata
    local image=$(python3 -c "
import json
data = json.load(open('$metadata_file'))
if 'image' in data:
    image = data['image']
    tag_separator = image.rfind(':')
    if tag_separator > image.rfind('/'):
        image = image[:tag_separator]
    print(image)
else:
    print('')
" 2>/dev/null || echo "")

    echo "$image"
}

# Function to get image name by matching Dockerfile directory to compose build.context
get_image_from_build_context() {
    local ext_path=$1
    local dockerfile_dir=$2  # path to directory containing Dockerfile
    local compose_file="$ext_path/docker-compose.yml"

    if [[ ! -f "$compose_file" ]]; then
        echo ""
        return
    fi

    local image=$(python3 -c "
import yaml, os, sys

compose_file = '$compose_file'
ext_path = '$ext_path'
dockerfile_dir = os.path.realpath('$dockerfile_dir')
image_prefix = '$IMAGE_PREFIX'
ext_name = os.path.basename(ext_path)

with open(compose_file) as f:
    data = yaml.safe_load(f)

for svc_name, svc in (data.get('services') or {}).items():
    if 'build' not in svc:
        continue
    build = svc['build']
    if isinstance(build, str):
        context = build
    elif isinstance(build, dict):
        context = build.get('context', '.')
    else:
        continue

    abs_context = os.path.realpath(os.path.join(os.path.dirname(compose_file), context))

    if abs_context == dockerfile_dir:
        if 'image' in svc:
            image = svc['image']
            last_slash = image.rfind('/')
            last_colon = image.rfind(':')
            if last_colon > last_slash:
                image = image[:last_colon]
            print(image)
        else:
            print(f'{image_prefix}/{ext_name}-{svc_name}')
        sys.exit(0)

print('')
" 2>/dev/null || echo "")

    echo "$image"
}

# Function to check if extension has local source
has_local_source() {
    local ext_path=$1

    # Check for Dockerfile in root or subdirectories
    if [[ -f "$ext_path/Dockerfile" ]]; then
        return 0
    fi

    # Check for service directories with Dockerfiles
    for dir in "$ext_path"/*; do
        if [[ -d "$dir" ]] && [[ -f "$dir/Dockerfile" ]]; then
            return 0
        fi
    done

    return 1
}

# Get the versioned tag based on stage
# - dev:   1.0.0-dev
# - stage: 1.0.0-stage
# - prod:  1.0.0
get_stage_tag() {
    local version=$1
    case "$STAGE" in
        dev)
            echo "${version}-dev"
            ;;
        stage)
            echo "${version}-stage"
            ;;
        prod)
            echo "${version}"
            ;;
    esac
}

# Function to verify an image exists locally
verify_image_exists() {
    local image_with_tag=$1
    docker image inspect "$image_with_tag" &>/dev/null
}

strip_registry_host() {
    local image_name=$1
    local first_segment="${image_name%%/*}"

    if [[ "$image_name" == */* ]] && [[ "$first_segment" == *.* || "$first_segment" == *:* || "$first_segment" == "localhost" ]]; then
        printf '%s\n' "${image_name#*/}"
        return 0
    fi

    printf '%s\n' "${image_name}"
}

build_effective_image_name() {
    local image_name=$1

    if [[ -z "${REGISTRY}" ]]; then
        printf '%s\n' "${image_name}"
        return 0
    fi

    printf '%s%s\n' "${REGISTRY}" "$(strip_registry_host "${image_name}")"
}

get_effective_registry_prefix() {
    if [[ -n "${REGISTRY}" ]]; then
        local stripped="${REGISTRY%/}"
        printf '%s\n' "${stripped}"
        return 0
    fi

    printf '%s\n' "${IMAGE_PREFIX}"
}

# Function to publish an image (verify/build then push)
publish_image() {
    local image_name=$1
    local version=$2
    local build_context=$3

    local full_image
    full_image="$(build_effective_image_name "${image_name}")"
    local stage_tag=$(get_stage_tag "$version")
    local image_with_tag="${full_image}:${stage_tag}"

    echo -e "${BLUE}Publishing ${image_with_tag} (stage: ${STAGE})${NC}"

    if [[ "$BUILD" == "true" ]]; then
        # Build multi-arch images and push directly using buildx
        if [[ "$DRY_RUN" == "true" ]]; then
            echo "  [DRY RUN] docker buildx build --push --platform ${PLATFORMS} -t ${image_with_tag} ${build_context}"
        else
            echo "  Building and pushing ${image_with_tag} for ${PLATFORMS}..."
            docker buildx build --push --platform "${PLATFORMS}" -t "${image_with_tag}" "${build_context}"
            echo -e "  ${GREEN}✓ Build and push complete${NC}"
        fi
    else
        # Verify the image exists locally and push (single-arch)
        if [[ "$DRY_RUN" == "true" ]]; then
            echo "  [DRY RUN] Verifying ${image_with_tag} exists locally"
        else
            echo "  Verifying ${image_with_tag} exists locally..."
            if ! verify_image_exists "${image_with_tag}"; then
                # Attempt to retag from -dev image (common after 'make build')
                local dev_tag="${full_image}:${version}-dev"
                if [[ "$STAGE" != "dev" ]] && verify_image_exists "${dev_tag}"; then
                    echo -e "  ${YELLOW}Image not found as ${stage_tag}, retagging from ${version}-dev${NC}"
                    docker tag "${dev_tag}" "${image_with_tag}"
                    echo -e "  ${GREEN}✓ Retagged ${dev_tag} -> ${image_with_tag}${NC}"
                else
                    echo -e "  ${RED}✗ Image not found: ${image_with_tag}${NC}"
                    echo -e "  ${YELLOW}Hint: Run 'make build' first, or use --build flag for multi-arch${NC}"
                    return 1
                fi
            else
                echo -e "  ${GREEN}✓ Image found${NC}"
            fi
        fi

        # Push the image (never push :latest - prod should reference specific versions)
        if [[ "$DRY_RUN" == "true" ]]; then
            echo "  [DRY RUN] docker push ${image_with_tag}"
        else
            echo "  Pushing ${image_with_tag}..."
            docker push "${image_with_tag}"
            echo -e "  ${GREEN}✓ Push complete${NC}"
        fi
    fi
}

# Function to process an extension
process_extension() {
    local ext_type=$1
    local ext_name=$2
    local ext_path="${REPO_ROOT}/${ext_type}s/${ext_name}"

    if ! has_local_source "$ext_path"; then
        echo -e "${YELLOW}Skipping ${ext_type}/${ext_name} - no local source${NC}"
        return
    fi

    local version=$(get_version "$ext_path")
    if [[ -z "$version" ]]; then
        echo -e "${RED}Error: No version found for ${ext_type}/${ext_name}${NC}"
        return 1
    fi

    echo -e "\n${BLUE}=== Processing ${ext_type}/${ext_name} ${version} ===${NC}"

    # Check if it's a multi-service app
    if [[ -f "$ext_path/docker-compose.yml" || -f "$ext_path/docker-compose.appgarden.yml" ]]; then
        # Look for service directories with Dockerfiles
        for dir in "$ext_path"/*; do
            if [[ -d "$dir" ]] && [[ -f "$dir/Dockerfile" ]]; then
                local service_name=$(basename "$dir")
                # compose build.context → kamiwaza.json → convention
                local image_name=$(get_image_from_build_context "$ext_path" "$dir")
                if [[ -z "$image_name" ]]; then
                    image_name=$(get_image_name "$ext_path")
                    if [[ -z "$image_name" ]]; then
                        image_name="${IMAGE_PREFIX}/${ext_name}-${service_name}"
                    else
                        image_name="${image_name}-${service_name}"
                    fi
                fi

                publish_image "$image_name" "$version" "$dir"
            fi
        done

        # Check root directory for single Dockerfile
        if [[ -f "$ext_path/Dockerfile" ]]; then
            local image_name=$(get_image_from_build_context "$ext_path" "$ext_path")
            if [[ -z "$image_name" ]]; then
                image_name=$(get_image_name "$ext_path")
            fi
            if [[ -z "$image_name" ]]; then
                image_name="${IMAGE_PREFIX}/${ext_name}"
            fi
            publish_image "$image_name" "$version" "$ext_path"
        fi
    else
        # Single service extension
        if [[ -f "$ext_path/Dockerfile" ]]; then
            local image_name=$(get_image_from_build_context "$ext_path" "$ext_path")
            if [[ -z "$image_name" ]]; then
                image_name=$(get_image_name "$ext_path")
            fi
            if [[ -z "$image_name" ]]; then
                image_name="${IMAGE_PREFIX}/${ext_name}"
            fi
            publish_image "$image_name" "$version" "$ext_path"
        fi
    fi
}

# Main execution
main() {
    echo "Publishing Docker images for Kamiwaza extensions"
    echo "================================================"
    echo -e "Image prefix: ${BLUE}${IMAGE_PREFIX}${NC}"
    echo -e "Stage: ${BLUE}${STAGE}${NC}"

    validate_image_prefix "${IMAGE_PREFIX}"

    if [[ "${DRY_RUN}" != "true" ]]; then
        authenticate_registry "true" "$(get_effective_registry_prefix)"
    fi

    case "$STAGE" in
        dev)
            echo "  Tags: version-dev"
            ;;
        stage)
            echo "  Tags: version-stage"
            ;;
        prod)
            echo "  Tags: version (no suffix)"
            ;;
    esac

    if [[ "$DRY_RUN" == "true" ]]; then
        echo -e "${YELLOW}DRY RUN MODE - No images will be pushed${NC}"
    fi

    if [[ "$BUILD" == "true" ]]; then
        echo -e "${BLUE}BUILD MODE - Multi-arch images will be built and pushed${NC}"
        echo "  Platforms: ${PLATFORMS}"
    else
        echo -e "${BLUE}VERIFY MODE - Images must exist locally (use --build for multi-arch)${NC}"
    fi

    if [[ -n "$REGISTRY" ]]; then
        echo "Registry prefix: $REGISTRY"
    fi

    if [[ -n "$FILTER_TYPE" ]] && [[ -n "$FILTER_NAME" ]]; then
        echo -e "Filter: ${BLUE}${FILTER_TYPE}/${FILTER_NAME}${NC}"
    fi

    # If filtering to a specific extension, process only that one
    if [[ -n "$FILTER_TYPE" ]] && [[ -n "$FILTER_NAME" ]]; then
        process_extension "$FILTER_TYPE" "$FILTER_NAME"
    else
        # Process all apps
        if [[ -z "$FILTER_TYPE" ]] || [[ "$FILTER_TYPE" == "app" ]]; then
            if [[ -d "${REPO_ROOT}/apps" ]]; then
                for ext_path in "${REPO_ROOT}/apps"/*; do
                    if [[ -d "$ext_path" ]] && [[ ! "$(basename "$ext_path")" =~ ^\. ]]; then
                        process_extension "app" "$(basename "$ext_path")"
                    fi
                done
            fi
        fi

        # Process all services
        if [[ -z "$FILTER_TYPE" ]] || [[ "$FILTER_TYPE" == "service" ]]; then
            if [[ -d "${REPO_ROOT}/services" ]]; then
                for ext_path in "${REPO_ROOT}/services"/*; do
                    if [[ -d "$ext_path" ]] && [[ ! "$(basename "$ext_path")" =~ ^\. ]]; then
                        process_extension "service" "$(basename "$ext_path")"
                    fi
                done
            fi
        fi

        # Process all tools
        if [[ -z "$FILTER_TYPE" ]] || [[ "$FILTER_TYPE" == "tool" ]]; then
            if [[ -d "${REPO_ROOT}/tools" ]]; then
                for ext_path in "${REPO_ROOT}/tools"/*; do
                    if [[ -d "$ext_path" ]] && [[ ! "$(basename "$ext_path")" =~ ^\. ]]; then
                        process_extension "tool" "$(basename "$ext_path")"
                    fi
                done
            fi
        fi
    fi

    echo -e "\n${GREEN}✓ Publishing complete${NC}"
}

# Run main
main
