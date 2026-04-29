#!/bin/bash
#
# Build Docker images for extensions
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Parse arguments
TYPE="${1:-}"
NAME="${2:-}"
NO_CACHE="${3:-}"

# Multi-arch build settings
PUSH_MODE="${PUSH_MODE:-false}"
PLATFORMS="${PLATFORMS:-}"
if [[ -n "${IMAGE_PREFIX:-}" ]]; then
    IMAGE_PREFIX="$(printf '%s' "${IMAGE_PREFIX%/}" | tr '[:upper:]' '[:lower:]')"
else
    IMAGE_PREFIX="$("${SCRIPT_DIR}/default-image-prefix.sh")"
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m'

docker_cli() {
    if [[ -n "${DOCKER_CONTEXT:-}" ]]; then
        docker --context "$DOCKER_CONTEXT" "$@"
    else
        docker "$@"
    fi
}

# Shared registry auth helpers (validate_image_prefix, authenticate_registry).
# Sourced after docker_cli so registry-auth.sh uses our context-aware wrapper.
REGISTRY_AUTH_LIB="${SCRIPT_DIR}/lib/registry-auth.sh"
if [[ ! -f "${REGISTRY_AUTH_LIB}" ]]; then
    echo -e "${RED}Error: Missing registry auth library at ${REGISTRY_AUTH_LIB}${NC}"
    exit 1
fi
# shellcheck source=lib/registry-auth.sh
source "${REGISTRY_AUTH_LIB}"

ensure_container_engine() {
    if docker_cli info >/dev/null 2>&1; then
        return 0
    fi

    # Fallback for users who switched to Podman but still have Docker Desktop as default context.
    if [[ -z "${DOCKER_CONTEXT:-}" ]] && docker context inspect podman >/dev/null 2>&1; then
        if docker --context podman info >/dev/null 2>&1; then
            export DOCKER_CONTEXT=podman
            echo -e "${YELLOW}⚠ Docker default context unavailable; using DOCKER_CONTEXT=podman for this build.${NC}"
            return 0
        fi
    fi

    local current_context
    current_context="$(docker context show 2>/dev/null || echo "unknown")"
    echo -e "${RED}Error: unable to connect to container engine.${NC}"
    echo "  Current docker context: ${current_context}"
    echo "  DOCKER_HOST: ${DOCKER_HOST:-<unset>}"
    echo ""
    echo "If you're using Podman, run one of:"
    echo "  export DOCKER_CONTEXT=podman"
    echo "  docker context use podman"
    return 1
}

usage() {
    echo "Usage: $0 <type> <name> [--no-cache]"
    echo "       $0 all [--no-cache]"
    echo ""
    echo "Options:"
    echo "  --no-cache    Build without using Docker cache"
    echo ""
    echo "Environment variables:"
    echo "  PUSH_MODE=true          Push to registry instead of loading locally (enables multi-arch)"
    echo "  PLATFORMS=<platforms>   Comma-separated platforms (e.g., linux/amd64,linux/arm64)"
    echo "                          Default for PUSH_MODE: linux/amd64,linux/arm64"
    echo "  IMAGE_PREFIX=<prefix>   Defaults to ghcr.io/<github-org>/<repo-name>/images"
    echo ""
    echo "Examples:"
    echo "  $0 app kaizen-app                          # Build specific app (local, single-arch)"
    echo "  $0 app kaizen-app --no-cache               # Build without cache"
    echo "  $0 service service-milvus                  # Build specific service"
    echo "  $0 tool websearch-tool                     # Build specific tool"
    echo "  $0 all                                     # Build all extensions"
    echo "  $0 all --no-cache                          # Build all without cache"
    echo "  PUSH_MODE=true $0 app kaizen-app           # Build and push multi-arch"
    echo "  PUSH_MODE=true PLATFORMS=linux/amd64 $0 app kaizen-app  # Push single arch"
    exit 1
}

# Function to get image name from metadata or docker-compose
get_image_name() {
    local ext_path=$1
    local service_name=${2:-web}
    local metadata_file="$ext_path/kamiwaza.json"

    # First, try to get image from kamiwaza.json (for tools)
    if [[ -f "$metadata_file" ]]; then
        local image=$(python3 -c "
import json
data = json.load(open('$metadata_file'))
if 'image' in data:
    image = data['image'].split('@', 1)[0]
    tag_separator = image.rfind(':')
    if tag_separator > image.rfind('/'):
        image = image[:tag_separator]
    print(image)
" 2>/dev/null || echo "")

        if [[ -n "$image" ]]; then
            echo "$image"
            return
        fi
    fi

    # For apps, try to extract from docker-compose.yml
    local compose_file="$ext_path/docker-compose.yml"
    if [[ -f "$compose_file" ]]; then
        local image=$(python3 -c "
import yaml
try:
    with open('$compose_file') as f:
        data = yaml.safe_load(f)
    if 'services' in data and '$service_name' in data['services']:
        service = data['services']['$service_name']
        if 'image' in service:
            # Extract just the image name without tag
            image = service['image'].split('@', 1)[0]
            tag_separator = image.rfind(':')
            if tag_separator > image.rfind('/'):
                image = image[:tag_separator]
            print(image)
except:
    pass
" 2>/dev/null || echo "")

        if [[ -n "$image" ]]; then
            echo "$image"
            return
        fi
    fi

    echo ""
}

# Function to get version from metadata (always adds -dev suffix for local builds)
get_version() {
    local ext_path=$1
    local metadata_file="$ext_path/kamiwaza.json"

    if [[ ! -f "$metadata_file" ]]; then
        echo "latest-dev"
        return
    fi

    local version=$(python3 -c "
import json
data = json.load(open('$metadata_file'))
print(data.get('version', 'latest'))
" 2>/dev/null || echo "latest")

    # Always add -dev suffix for local builds
    # CI/CD handles promotion to stage/prod by retagging
    echo "${version}-dev"
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

# Function to build a single service
build_service() {
    local service_path=$1
    local ext_path=$2  # Pass extension path explicitly
    local build_platform="${PLATFORM:-${DOCKER_DEFAULT_PLATFORM:-}}"
    local output_flag="--load"

    if [[ "$PUSH_MODE" == "true" ]]; then
        output_flag="--push"
        # Default to multi-arch when pushing
        if [[ -z "$build_platform" ]]; then
            build_platform="${PLATFORMS:-linux/amd64,linux/arm64}"
        fi
    else
        # --load mode: single platform only
        if [[ "$build_platform" == *","* ]]; then
            echo -e "${YELLOW}⚠ Multi-arch not supported with --load; using first platform only.${NC}"
            build_platform="${build_platform%%,*}"
        fi
    fi

    # For root-level services, use 'web' as the default service name
    local service_name
    if [[ "$service_path" == "$ext_path" ]]; then
        service_name="web"
    else
        service_name=$(basename "$service_path")
    fi

    local ext_name=$(basename "$ext_path")
    local ext_type=$(basename $(dirname "$ext_path"))

    # Remove trailing 's' from type
    ext_type="${ext_type%s}"

    # Determine image name: compose build.context → kamiwaza.json → convention
    local image_name=$(get_image_from_build_context "$ext_path" "$service_path")
    if [[ -z "$image_name" ]]; then
        image_name=$(get_image_name "$ext_path" "$service_name")
    fi
    if [[ -z "$image_name" ]]; then
        image_name="${IMAGE_PREFIX}/${ext_name}-${service_name}"
    fi

    local version=$(get_version "$ext_path")

    echo -e "${BLUE}Building ${ext_type}/${ext_name}/${service_name}...${NC}"
    echo "  Image: ${image_name}:${version}"
    if [[ "$PUSH_MODE" == "true" ]]; then
        echo "  Mode: push (multi-arch)"
        echo "  Platforms: ${build_platform}"
    else
        echo "  Mode: load (local)"
    fi

    if [[ -f "$service_path/Dockerfile" ]]; then
        # Generate build timestamp
        BUILD_TIME=$(date -u +"%Y-%m-%d %H:%M:%S UTC")

        # Determine docker build flags
        local build_flags=""
        if [[ "$NO_CACHE" == "--no-cache" ]]; then
            build_flags="--no-cache"
        fi

        # Build with timestamp for frontend services
        # For local builds (--load), create both version tag and :latest for dev convenience
        # For push builds (--push), only version tag (no :latest pushed to registry)
        local tag_args="-t ${image_name}:${version}"
        if [[ "$output_flag" == "--load" ]]; then
            tag_args="$tag_args -t ${image_name}:latest"
        fi

        if [[ "$service_name" == "frontend" ]]; then
            docker_cli buildx build $build_flags ${build_platform:+--platform "$build_platform"} $output_flag --build-arg BUILD_TIME="$BUILD_TIME" $tag_args "$service_path" || {
                echo -e "${RED}✗ Failed to build ${image_name}${NC}"
                return 1
            }
        else
            docker_cli buildx build $build_flags ${build_platform:+--platform "$build_platform"} $output_flag $tag_args "$service_path" || {
                echo -e "${RED}✗ Failed to build ${image_name}${NC}"
                return 1
            }
        fi

        echo -e "${GREEN}✓ Successfully built ${image_name}:${version}${NC}"
    else
        echo -e "${YELLOW}⚠ No Dockerfile found in ${service_path}${NC}"
        return 1
    fi
}

# Function to verify external images
verify_external_images() {
    local ext_path=$1
    local ext_name=$(basename "$ext_path")
    local images=()

    # Extract images from kamiwaza.json
    if [[ -f "$ext_path/kamiwaza.json" ]]; then
        local image=$(python3 -c "
import json
data = json.load(open('$ext_path/kamiwaza.json'))
if 'image' in data:
    print(data['image'])
" 2>/dev/null)
        if [[ -n "$image" ]]; then
            images+=("$image")
        fi
    fi

    # Extract images from docker-compose.appgarden.yml
    if [[ -f "$ext_path/docker-compose.appgarden.yml" ]]; then
        local compose_images=$(python3 -c "
import yaml
data = yaml.safe_load(open('$ext_path/docker-compose.appgarden.yml'))
if 'services' in data:
    for service, config in data['services'].items():
        if 'image' in config:
            print(config['image'])
" 2>/dev/null || true)
        if [[ -n "$compose_images" ]]; then
            while IFS= read -r img; do
                images+=("$img")
            done <<< "$compose_images"
        fi
    fi

    if [[ ${#images[@]} -eq 0 ]]; then
        echo -e "${RED}No images found in metadata or compose file${NC}"
        return 1
    fi

    echo "  External extension - verifying images:"
    local all_found=true
    for image in "${images[@]}"; do
        # Check if image exists locally
        if docker_cli image inspect "$image" >/dev/null 2>&1; then
            echo -e "  ${GREEN}✓ ${image} (local)${NC}"
        else
            echo -e "  ${YELLOW}⚠ ${image} (not found locally - must exist in registry)${NC}"
            all_found=false
        fi
    done

    if [[ "$all_found" == "true" ]]; then
        echo -e "${GREEN}✓ All images verified${NC}"
    else
        echo -e "${YELLOW}⚠ Some images not found locally - ensure they exist in registry${NC}"
    fi

    return 0
}

# Function to build an extension
build_extension() {
    local ext_type=$1
    local ext_name=$2
    local ext_path="${REPO_ROOT}/${ext_type}s/${ext_name}"

    if [[ ! -d "$ext_path" ]]; then
        echo -e "${RED}Error: Extension not found: ${ext_type}s/${ext_name}${NC}"
        return 1
    fi

    echo -e "\n${BLUE}=== Building ${ext_type}/${ext_name} ===${NC}"

    # Deer Flow keeps Dockerfiles at the source repo root while this App Garden
    # package lives under appgarden/apps/deer-flow. Compose preserves the correct
    # repo-root build contexts, so use it for this package instead of the template
    # service-directory convention.
    if [[ "$ext_name" == "deer-flow" && -f "$ext_path/docker-compose.yml" ]]; then
        local compose_cli
        if docker compose version >/dev/null 2>&1; then
            compose_cli="docker compose"
        else
            compose_cli="docker-compose"
        fi
        local build_flags=()
        if [[ "$NO_CACHE" == "--no-cache" ]]; then
            build_flags+=(--no-cache)
        fi
        IMAGE_PREFIX="${IMAGE_PREFIX}" $compose_cli -f "$ext_path/docker-compose.yml" build "${build_flags[@]}"
        return
    fi

    # Check if it's a multi-service app
    if [[ -f "$ext_path/docker-compose.yml" || -f "$ext_path/docker-compose.appgarden.yml" ]]; then
        # Look for service directories with Dockerfiles
        local found_services=false
        for dir in "$ext_path"/*; do
            if [[ -d "$dir" ]] && [[ -f "$dir/Dockerfile" ]]; then
                build_service "$dir" "$ext_path"
                found_services=true
            fi
        done

        # If no service directories, check root
        if [[ "$found_services" == "false" ]] && [[ -f "$ext_path/Dockerfile" ]]; then
            build_service "$ext_path" "$ext_path"
        elif [[ "$found_services" == "false" ]]; then
            # No Dockerfile found - check if this is an external extension
            echo -e "${YELLOW}No Dockerfile found - checking for external images${NC}"
            verify_external_images "$ext_path"
        fi
    else
        # Single service extension
        if [[ -f "$ext_path/Dockerfile" ]]; then
            build_service "$ext_path" "$ext_path"
        else
            echo -e "${YELLOW}No Dockerfile found - checking for external images${NC}"
            verify_external_images "$ext_path"
        fi
    fi
}

# Function to build all extensions
build_all() {
    echo "Building all extensions..."

    # Build all apps
    if [[ -d "${REPO_ROOT}/apps" ]]; then
        for app_path in "${REPO_ROOT}/apps"/*; do
            if [[ -d "$app_path" ]] && [[ ! "$(basename "$app_path")" =~ ^\. ]]; then
                build_extension "app" "$(basename "$app_path")"
            fi
        done
    fi

    # Build all services
    if [[ -d "${REPO_ROOT}/services" ]]; then
        for service_path in "${REPO_ROOT}/services"/*; do
            if [[ -d "$service_path" ]] && [[ ! "$(basename "$service_path")" =~ ^\. ]]; then
                build_extension "service" "$(basename "$service_path")"
            fi
        done
    fi

    # Build all tools
    if [[ -d "${REPO_ROOT}/tools" ]]; then
        for tool_path in "${REPO_ROOT}/tools"/*; do
            if [[ -d "$tool_path" ]] && [[ ! "$(basename "$tool_path")" =~ ^\. ]]; then
                build_extension "tool" "$(basename "$tool_path")"
            fi
        done
    fi
}

# Main logic
if ! ensure_container_engine; then
    exit 1
fi

if [[ "$PUSH_MODE" == "true" ]]; then
    authenticate_registry "true"
else
    validate_image_prefix "${IMAGE_PREFIX:-}" || exit 1
fi

if [[ "$TYPE" == "all" ]]; then
    build_all
elif [[ -n "$TYPE" ]] && [[ -n "$NAME" ]]; then
    build_extension "$TYPE" "$NAME"
else
    usage
fi
