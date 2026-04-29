#!/usr/bin/env bash
#
# Resolve the default extension image prefix for this repository.
#
# Priority:
#   1. image_prefix from .copier-answers.yml
#   2. legacy docker_org / organization from .copier-answers.yml
#   3. github_org from .copier-answers.yml + repo name
#   4. GitHub origin remote owner/repo
#   5. Fallback: ghcr.io/kamiwaza-internal/<repo-name>/images
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DEFAULT_GITHUB_ORG="kamiwaza-internal"

strip_quotes() {
    local value="${1:-}"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    printf '%s\n' "${value}"
}

normalize_name() {
    local value="${1:-}"
    value="$(strip_quotes "${value}")"
    value="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')"
    value="${value// /-}"
    value="${value//_/-}"
    printf '%s\n' "${value}"
}

normalize_prefix() {
    local value="${1:-}"
    local -a segments normalized_segments

    value="$(strip_quotes "${value}")"
    value="${value%/}"
    IFS='/' read -r -a segments <<< "${value}"

    for segment in "${segments[@]}"; do
        normalized_segments+=("$(normalize_name "${segment}")")
    done

    local IFS='/'
    printf '%s\n' "${normalized_segments[*]}"
}

read_copier_value() {
    local key="$1"
    local answers_file="${REPO_ROOT}/.copier-answers.yml"

    if [[ ! -f "${answers_file}" ]]; then
        return 1
    fi

    local raw_value
    raw_value="$(
        awk -v key="${key}" '
            index($0, key ":") == 1 {
                value = substr($0, length(key) + 2)
                sub(/^[[:space:]]+/, "", value)
                sub(/[[:space:]]+#.*$/, "", value)
                sub(/[[:space:]]+$/, "", value)
                print value
                exit
            }
        ' "${answers_file}"
    )"

    if [[ -z "${raw_value}" ]]; then
        return 1
    fi

    strip_quotes "${raw_value}"
}

read_git_remote() {
    local remote_url owner repo
    remote_url="$(git -C "${REPO_ROOT}" config --get remote.origin.url 2>/dev/null || true)"

    if [[ -z "${remote_url}" ]]; then
        return 1
    fi

    remote_url="${remote_url%/}"
    remote_url="${remote_url%.git}"

    if [[ "${remote_url}" =~ ^git@github\.com:([^/]+)/([^/]+)$ ]]; then
        owner="${BASH_REMATCH[1]}"
        repo="${BASH_REMATCH[2]}"
    elif [[ "${remote_url}" =~ ^ssh://git@github\.com(:[0-9]+)?/([^/]+)/([^/]+)$ ]]; then
        owner="${BASH_REMATCH[2]}"
        repo="${BASH_REMATCH[3]}"
    elif [[ "${remote_url}" =~ ^(git\+)?https?://([^@/]+@)?github\.com/([^/]+)/([^/]+)$ ]]; then
        owner="${BASH_REMATCH[3]}"
        repo="${BASH_REMATCH[4]}"
    else
        return 1
    fi

    printf '%s/%s\n' "${owner}" "${repo}"
}

main() {
    local repo_name github_org legacy_prefix remote_ref image_prefix

    repo_name="$(basename "${REPO_ROOT}")"

    image_prefix="$(read_copier_value image_prefix || true)"
    if [[ -n "${image_prefix}" ]]; then
        printf '%s\n' "$(normalize_prefix "${image_prefix}")"
        return 0
    fi

    legacy_prefix="$(read_copier_value docker_org || true)"
    if [[ -z "${legacy_prefix}" ]]; then
        legacy_prefix="$(read_copier_value organization || true)"
    fi
    if [[ -n "${legacy_prefix}" ]]; then
        printf '%s\n' "$(normalize_prefix "${legacy_prefix}")"
        return 0
    fi

    github_org="$(read_copier_value github_org || true)"

    remote_ref="$(read_git_remote || true)"
    if [[ -n "${remote_ref}" ]]; then
        if [[ -z "${github_org}" ]]; then
            github_org="${remote_ref%%/*}"
        fi
        repo_name="${remote_ref##*/}"
    fi

    if [[ -z "${github_org}" ]]; then
        github_org="${DEFAULT_GITHUB_ORG}"
    fi

    github_org="$(normalize_name "${github_org}")"
    repo_name="$(normalize_name "${repo_name}")"

    printf 'ghcr.io/%s/%s/images\n' "${github_org}" "${repo_name}"
}

main "$@"
