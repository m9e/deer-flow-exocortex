#!/bin/bash
#
# Shared helpers for container registry authentication.
#

registry_auth_log() {
    local level="$1"
    local message="$2"

    local color=""
    case "$level" in
        info) color="${BLUE:-}" ;;
        success) color="${GREEN:-}" ;;
        warn) color="${YELLOW:-}" ;;
        error) color="${RED:-}" ;;
    esac

    if [[ -n "${NC:-}" ]]; then
        echo -e "${color}${message}${NC}"
    else
        echo "${message}"
    fi
}

# Callers (e.g. build-extension.sh) may pre-define docker_cli to route through
# an alternate container engine/context (e.g. podman).
if ! declare -F docker_cli >/dev/null 2>&1; then
    docker_cli() {
        docker "$@"
    }
fi

validate_image_prefix() {
    local image_prefix="${1:-${IMAGE_PREFIX:-}}"
    local pattern='^[a-z0-9]+([._-][a-z0-9]+)*(:[0-9]+)?(/[a-z0-9]+([._-][a-z0-9]+)*)*$'

    if [[ -z "${image_prefix}" ]]; then
        registry_auth_log error "Error: IMAGE_PREFIX cannot be empty"
        return 1
    fi

    if [[ "${image_prefix}" == */ ]]; then
        registry_auth_log error "Error: IMAGE_PREFIX must not end with '/' (${image_prefix})"
        return 1
    fi

    if [[ ! "${image_prefix}" =~ ${pattern} ]]; then
        registry_auth_log error \
            "Error: Invalid IMAGE_PREFIX '${image_prefix}'. Use lowercase Docker names (e.g., 'ghcr.io/my-org/my-repo/images')"
        return 1
    fi

    return 0
}

get_ghcr_token() {
    local token="${GHCR_TOKEN:-${GH_TOKEN:-}}"

    if [[ -z "${token}" ]] && command -v gh &>/dev/null; then
        token="$(gh auth token 2>/dev/null || true)"
    fi

    echo "${token}"
}

get_ghcr_username() {
    if [[ -n "${GHCR_USERNAME:-}" ]]; then
        echo "${GHCR_USERNAME}"
        return 0
    fi

    if [[ -n "${GITHUB_ACTOR:-}" ]]; then
        echo "${GITHUB_ACTOR}"
        return 0
    fi

    if command -v gh &>/dev/null; then
        local login
        login="$(gh api user -q .login 2>/dev/null || true)"
        if [[ -n "${login}" ]]; then
            echo "${login}"
            return 0
        fi
    fi

    return 1
}

authenticate_registry() {
    local require_auth="${1:-false}"
    local target_prefix="${2:-${IMAGE_PREFIX:-}}"

    target_prefix="${target_prefix%/}"

    if ! validate_image_prefix "${target_prefix}"; then
        return 1
    fi

    if [[ "${target_prefix}" != ghcr.io/* ]]; then
        return 0
    fi

    registry_auth_log info "Authenticating with GitHub Container Registry..."

    local token
    token="$(get_ghcr_token)"
    if [[ -z "${token}" ]]; then
        if [[ "${require_auth}" == "true" ]]; then
            registry_auth_log error "Error: No GHCR token found. Set GHCR_TOKEN or GH_TOKEN, or run 'gh auth login'"
            return 1
        fi
        registry_auth_log warn "Warning: No GHCR token found. Continuing without authentication."
        return 0
    fi

    local username
    if ! username="$(get_ghcr_username)"; then
        if [[ "${require_auth}" == "true" ]]; then
            registry_auth_log error "Error: Could not determine GHCR username. Set GHCR_USERNAME or GITHUB_ACTOR."
            return 1
        fi
        registry_auth_log warn "Warning: Could not determine GHCR username. Continuing without authentication."
        return 0
    fi

    if echo "${token}" | docker_cli login ghcr.io --username "${username}" --password-stdin; then
        registry_auth_log success "✓ Authenticated with GHCR as ${username}"
        return 0
    fi

    registry_auth_log error "Error: GHCR authentication failed."
    return 1
}
