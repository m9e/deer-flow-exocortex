#!/bin/bash
#
# Load exported Docker images into Kind cluster's containerd
#
# Reads the manifest.json from the docker-images export directory,
# imports each tar file into Kind's containerd, and normalizes image
# references for pull/tag operations.
#
# Usage:
#   ./scripts/kind-load-images.sh [OPTIONS]
#
# Options:
#   --repo-version VER    Registry version (default: from .repo-version or 2)
#   --cluster NAME        Kind cluster name (default: kamiwaza-dev)
#   --dry-run             Show what would be done without importing
#   --skip-pull           Skip pulling images that weren't exported locally
#   -h, --help            Show this help message
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-kamiwaza-dev}"
REPO_VERSION=""
DRY_RUN=false
SKIP_PULL=false
CONTAINER_CLI="${CONTAINER_CLI:-}"

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Load exported Docker images into Kind cluster's containerd.

Options:
  --repo-version VER    Registry version (default: from .repo-version or 2)
  --cluster NAME        Kind cluster name (default: kamiwaza-dev)
  --dry-run             Show what would be done without importing
  --skip-pull           Skip pulling images that weren't exported locally
  -h, --help            Show this help message

Environment:
  KIND_CLUSTER_NAME     Same as --cluster option
  CONTAINER_CLI         Override container CLI (docker or podman)

Examples:
  # Load images for v3 extension into default Kind cluster
  $0 --repo-version 3

  # Load into a specific cluster
  $0 --cluster my-cluster --repo-version 3

  # Dry run
  $0 --repo-version 3 --dry-run
EOF
    exit 0
}

# Return success when the image already contains an explicit registry host.
# Examples:
#   ghcr.io/org/app:1.0.0   -> explicit
#   localhost/app:1.0.0     -> explicit
#   app:1.0.0               -> implicit (Docker Hub)
has_explicit_registry() {
    local image_ref="$1"
    local first_component
    first_component="${image_ref%%/*}"

    [[ "$image_ref" == */* ]] || return 1
    [[ "$first_component" == "localhost" || "$first_component" == *.* || "$first_component" == *:* ]]
}

# Normalize image reference for containerd operations.
# Fully-qualified refs are returned unchanged. Unqualified refs are
# prefixed with docker.io/.
normalize_image_ref() {
    local image_ref="$1"
    if has_explicit_registry "$image_ref"; then
        echo "$image_ref"
    else
        echo "docker.io/${image_ref}"
    fi
}

read_tar_repo_tags() {
    local tar_path="$1"

    python3 - "$tar_path" <<'PY'
import json
import sys
import tarfile

tar_path = sys.argv[1]

try:
    with tarfile.open(tar_path, "r") as archive:
        manifest = archive.extractfile("manifest.json")
        if manifest is None:
            raise FileNotFoundError("manifest.json not found in tar archive")
        entries = json.load(manifest)
except Exception as exc:
    print(f"Warning: Failed to read RepoTags from {tar_path}: {exc}", file=sys.stderr)
    sys.exit(0)

for entry in entries:
    for tag in entry.get("RepoTags", []):
        print(tag)
PY
}

image_ref_exists() {
    local image_ref="$1"

    "$CONTAINER_CLI" exec "$KIND_NODE" ctr -n k8s.io images ls 2>/dev/null \
        | awk '{print $1}' \
        | grep -Fx "$image_ref" >/dev/null 2>&1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --repo-version)
            REPO_VERSION="$2"
            shift 2
            ;;
        --cluster)
            KIND_CLUSTER_NAME="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-pull)
            SKIP_PULL=true
            shift
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

# Auto-detect repo version if not specified
if [[ -z "$REPO_VERSION" ]]; then
    if [[ -f "$REPO_ROOT/.repo-version" ]]; then
        REPO_VERSION=$(tr -d '[:space:]' < "$REPO_ROOT/.repo-version")
    else
        REPO_VERSION="2"
    fi
fi

# Map version to garden directory name
if [[ "$REPO_VERSION" == "1" ]]; then
    GARDEN_DIR="default"
else
    GARDEN_DIR="v${REPO_VERSION}"
fi

# Paths
BUILD_DIR="$REPO_ROOT/build/kamiwaza-extension-registry/garden/$GARDEN_DIR"
IMAGES_DIR="$BUILD_DIR/docker-images"
MANIFEST_FILE="$IMAGES_DIR/manifest.json"
KIND_NODE="${KIND_CLUSTER_NAME}-control-plane"

# Validate prerequisites
echo -e "${BLUE}Loading extension images into Kind cluster${NC}"
echo "  Cluster: ${KIND_CLUSTER_NAME}"
echo "  Repo version: ${REPO_VERSION}"
echo "  Images dir: ${IMAGES_DIR}"

if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "${YELLOW}DRY RUN MODE - No images will be imported${NC}"
fi

# Check manifest exists
if [[ ! -f "$MANIFEST_FILE" ]]; then
    echo -e "${RED}Error: Manifest not found at ${MANIFEST_FILE}${NC}"
    echo "Run 'make build-registry' first to export images."
    exit 1
fi

# Check Kind cluster exists (cache output to avoid repeated slow calls)
detect_kind_cluster() {
    local cluster="$1"

    # Try default context first
    local clusters
    clusters=$(kind get clusters 2>/dev/null || true)
    if echo "$clusters" | grep -qxF "$cluster"; then
        return 0
    fi

    # If DOCKER_CONTEXT is set, retry with DOCKER_HOST cleared (DOCKER_HOST overrides DOCKER_CONTEXT)
    if [[ -n "${DOCKER_CONTEXT:-}" ]]; then
        clusters=$(DOCKER_HOST= DOCKER_CONTEXT="${DOCKER_CONTEXT}" kind get clusters 2>/dev/null || true)
        if echo "$clusters" | grep -qxF "$cluster"; then
            unset DOCKER_HOST
            echo -e "${YELLOW}Detected Kind cluster after clearing DOCKER_HOST; using DOCKER_CONTEXT=${DOCKER_CONTEXT}.${NC}"
            return 0
        fi
    fi

    # Fallback for setups where Podman context exists but is not active
    if docker context inspect podman >/dev/null 2>&1; then
        clusters=$(DOCKER_HOST= DOCKER_CONTEXT=podman kind get clusters 2>/dev/null || true)
        if echo "$clusters" | grep -qxF "$cluster"; then
            export DOCKER_CONTEXT=podman
            unset DOCKER_HOST
            echo -e "${YELLOW}Detected Kind cluster via podman context; using DOCKER_CONTEXT=podman.${NC}"
            return 0
        fi
    fi

    return 1
}

if ! detect_kind_cluster "$KIND_CLUSTER_NAME"; then
    echo -e "${RED}Error: Kind cluster '${KIND_CLUSTER_NAME}' not found${NC}"
    echo "Available clusters:"
    kind get clusters 2>/dev/null || echo "  (none)"
    if [[ -z "${DOCKER_CONTEXT:-}" ]]; then
        echo ""
        echo "Hint: if you are on Podman, try:"
        echo "  export DOCKER_CONTEXT=podman"
    fi
    exit 1
fi

# Choose container CLI for talking to the kind node container.
# Align with DOCKER_CONTEXT when set: podman context → podman CLI, else docker.
if [[ -z "$CONTAINER_CLI" ]]; then
    if [[ "${DOCKER_CONTEXT:-}" == "podman" ]] && command -v podman >/dev/null 2>&1; then
        CONTAINER_CLI="podman"
    elif command -v docker >/dev/null 2>&1; then
        CONTAINER_CLI="docker"
    elif command -v podman >/dev/null 2>&1; then
        CONTAINER_CLI="podman"
    else
        echo -e "${RED}Error: Neither podman nor docker is available${NC}"
        exit 1
    fi
fi

# Check Kind node is accessible
if ! "$CONTAINER_CLI" exec "$KIND_NODE" true 2>/dev/null; then
    echo -e "${RED}Error: Cannot access Kind node '${KIND_NODE}'${NC}"
    echo "  Container CLI: ${CONTAINER_CLI}"
    exit 1
fi

# Parse manifest and load images
LOADED=0
SKIPPED=0
FAILED=0
PULLED=0

# Read image entries from manifest using Python (portable JSON parsing)
IMAGE_ENTRIES=$(python3 - "$MANIFEST_FILE" <<'PY' 2>/dev/null
import json
import sys

manifest_path = sys.argv[1]
with open(manifest_path) as manifest_file:
    manifest = json.load(manifest_file)
for name, info in manifest.get("images", {}).items():
    export_info = info.get("export", {})
    tar_file = export_info.get("file", "") or "-"
    success = export_info.get("success", False)
    exists = info.get("exists_locally", False)
    print(f"{name}\t{tar_file}\t{success}\t{exists}")
PY
) || {
    echo -e "${RED}Error: Failed to parse manifest${NC}"
    exit 1
}

echo ""

while IFS=$'\t' read -r IMAGE_NAME TAR_FILE EXPORT_SUCCESS EXISTS_LOCALLY; do
    [[ -z "$IMAGE_NAME" ]] && continue

    if [[ "$TAR_FILE" == "-" ]]; then
        TAR_FILE=""
    fi

    echo -e "${CYAN}Processing: ${IMAGE_NAME}${NC}"
    TARGET_IMAGE="$(normalize_image_ref "$IMAGE_NAME")"

    # Check if we have a tar file to import
    if [[ "$EXPORT_SUCCESS" == "True" ]] && [[ -n "$TAR_FILE" ]]; then
        TAR_PATH="$IMAGES_DIR/$TAR_FILE"

        if [[ ! -f "$TAR_PATH" ]]; then
            echo -e "  ${RED}Tar file not found: ${TAR_PATH}${NC}"
            FAILED=$((FAILED + 1))
            continue
        fi

        TAR_SIZE=$(du -h "$TAR_PATH" | cut -f1)
        echo -e "  Importing ${TAR_FILE} (${TAR_SIZE})..."

        if [[ "$DRY_RUN" == "true" ]]; then
            echo -e "  ${YELLOW}[DRY RUN] Would import ${TAR_FILE} and tag as ${TARGET_IMAGE}${NC}"
            LOADED=$((LOADED + 1))
            continue
        fi

        # Import tar into containerd
        if import_err=$("$CONTAINER_CLI" exec -i "$KIND_NODE" ctr -n k8s.io images import - < "$TAR_PATH" 2>&1); then
            echo -e "  ${GREEN}Imported into containerd${NC}"
        else
            echo -e "  ${RED}Failed to import${NC}"
            [[ -n "$import_err" ]] && echo -e "  ${RED}${import_err}${NC}"
            FAILED=$((FAILED + 1))
            continue
        fi

        # Find what name it was imported as and retag to the expected reference.
        # Images exported via podman save may retain localhost/ prefixes in manifest.json,
        # even when the registry entry expects an unqualified image name.
        IMPORTED=""
        while IFS= read -r repo_tag; do
            [[ -z "$repo_tag" ]] && continue

            if image_ref_exists "$repo_tag"; then
                IMPORTED="$repo_tag"
                break
            fi

            NORMALIZED_REPO_TAG="$(normalize_image_ref "$repo_tag")"
            if [[ "$NORMALIZED_REPO_TAG" != "$repo_tag" ]] && image_ref_exists "$NORMALIZED_REPO_TAG"; then
                IMPORTED="$NORMALIZED_REPO_TAG"
                break
            fi
        done < <(read_tar_repo_tags "$TAR_PATH")

        if [[ -z "$IMPORTED" ]]; then
            IMPORTED=$("$CONTAINER_CLI" exec "$KIND_NODE" ctr -n k8s.io images ls 2>/dev/null \
                | awk -v image="$IMAGE_NAME" '$1 == image { print $1; exit }')
        fi

        if [[ -z "$IMPORTED" ]]; then
            echo -e "  ${RED}Image not found in containerd after import${NC}"
            FAILED=$((FAILED + 1))
            continue
        fi

        echo -e "  Imported as: ${IMPORTED}"

        if [[ "$IMPORTED" != "$TARGET_IMAGE" ]]; then
            "$CONTAINER_CLI" exec "$KIND_NODE" ctr -n k8s.io images tag --force \
                "$IMPORTED" "$TARGET_IMAGE" 2>/dev/null && \
            echo -e "  ${GREEN}Tagged: ${TARGET_IMAGE}${NC}" || {
                echo -e "  ${RED}Failed to tag as ${TARGET_IMAGE}${NC}"
                FAILED=$((FAILED + 1))
                continue
            }
        else
            echo -e "  ${GREEN}Already tagged correctly${NC}"
        fi

        LOADED=$((LOADED + 1))

    elif "$CONTAINER_CLI" image inspect "$IMAGE_NAME" >/dev/null 2>&1 || \
         "$CONTAINER_CLI" image inspect "$TARGET_IMAGE" >/dev/null 2>&1; then
        # No export tar found, but the image exists in the active container engine.
        # Always load the normalized reference (TARGET_IMAGE) so containerd can satisfy
        # K8s pulls that expand unqualified refs to docker.io/<name>.
        echo -e "  No export tar found. Loading directly from local image store..."

        SOURCE_IMAGE="$IMAGE_NAME"
        if ! "$CONTAINER_CLI" image inspect "$SOURCE_IMAGE" >/dev/null 2>&1; then
            SOURCE_IMAGE="$TARGET_IMAGE"
        fi

        if [[ "$SOURCE_IMAGE" != "$TARGET_IMAGE" ]] && \
           ! "$CONTAINER_CLI" image inspect "$TARGET_IMAGE" >/dev/null 2>&1; then
            if "$CONTAINER_CLI" tag "$SOURCE_IMAGE" "$TARGET_IMAGE" >/dev/null 2>&1; then
                echo -e "  ${GREEN}Tagged locally: ${SOURCE_IMAGE} -> ${TARGET_IMAGE}${NC}"
            else
                echo -e "  ${RED}Failed to tag local image ${SOURCE_IMAGE} as ${TARGET_IMAGE}${NC}"
                FAILED=$((FAILED + 1))
                continue
            fi
        fi

        if [[ "$DRY_RUN" == "true" ]]; then
            echo -e "  ${YELLOW}[DRY RUN] Would run: kind load docker-image ${TARGET_IMAGE} --name ${KIND_CLUSTER_NAME}${NC}"
            LOADED=$((LOADED + 1))
            continue
        fi

        kind_err=$(kind load docker-image "$TARGET_IMAGE" --name "$KIND_CLUSTER_NAME" 2>&1) && {
            echo -e "  ${GREEN}Loaded via kind load docker-image${NC}"
            LOADED=$((LOADED + 1))
        } || {
            echo -e "  ${RED}Failed to load image via kind${NC}"
            [[ -n "$kind_err" ]] && echo -e "  ${RED}${kind_err}${NC}"
            FAILED=$((FAILED + 1))
        }

    elif [[ "$EXISTS_LOCALLY" == "False" ]] && [[ "$SKIP_PULL" == "false" ]]; then
        # Image not exported (e.g., postgres:15-alpine) — pull directly
        echo -e "  No local export. Pulling from registry..."

        if [[ "$DRY_RUN" == "true" ]]; then
            echo -e "  ${YELLOW}[DRY RUN] Would pull ${IMAGE_NAME}${NC}"
            PULLED=$((PULLED + 1))
            continue
        fi

        if "$CONTAINER_CLI" exec "$KIND_NODE" crictl pull "$TARGET_IMAGE" 2>/dev/null; then
            echo -e "  ${GREEN}Pulled: ${TARGET_IMAGE}${NC}"
            PULLED=$((PULLED + 1))
        else
            echo -e "  ${YELLOW}Could not pull ${IMAGE_NAME} (may need manual loading)${NC}"
            SKIPPED=$((SKIPPED + 1))
        fi

    else
        echo -e "  ${YELLOW}Skipped (no export, skip-pull enabled or not needed)${NC}"
        SKIPPED=$((SKIPPED + 1))
    fi

done <<< "$IMAGE_ENTRIES"

# Summary
echo ""
echo -e "${BLUE}=== Summary ===${NC}"
echo -e "  Loaded:  ${GREEN}${LOADED}${NC}"
[[ $PULLED -gt 0 ]] && echo -e "  Pulled:  ${GREEN}${PULLED}${NC}"
[[ $SKIPPED -gt 0 ]] && echo -e "  Skipped: ${YELLOW}${SKIPPED}${NC}"
[[ $FAILED -gt 0 ]] && echo -e "  Failed:  ${RED}${FAILED}${NC}"

# List imported images
if [[ "$DRY_RUN" == "false" ]] && [[ $LOADED -gt 0 || $PULLED -gt 0 ]]; then
    echo ""
    echo -e "${BLUE}Extension images in containerd:${NC}"
    "$CONTAINER_CLI" exec "$KIND_NODE" ctr -n k8s.io images ls 2>/dev/null \
        | grep -E "kamiwazaai/|ghcr.io/|postgres:" | awk '{printf "  %-60s %s\n", $1, $4}' || true
fi

if [[ $FAILED -gt 0 ]]; then
    echo ""
    echo -e "${RED}Some images failed to load. Check errors above.${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}Done.${NC}"
