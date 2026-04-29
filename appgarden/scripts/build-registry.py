#!/usr/bin/env python3
"""
Build registry files (apps.json and tools.json) from extension metadata.

This script scans apps/, services/, and tools/ directories, reads their
kamiwaza.json metadata files and docker-compose.appgarden.yml files, and
generates the consolidated registry files needed by Kamiwaza. Services are
published into apps.json (App Garden) alongside apps.

Supports both modern (2/3) and legacy (1) catalog formats:
- 2/3: garden/v{N}/ with kamiwaza_version constraints and images/ folder
- 1 (legacy): garden/default/ with app-garden-images/ folder (no version constraints)
"""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from image_prefix import get_image_prefix

IMAGE_PREFIX = get_image_prefix(script_path=__file__)


def is_modern_format(version: str) -> bool:
    """2+ uses modern format (images/, relative paths, kamiwaza_version)."""
    return version != "1"


def get_repo_version() -> str:
    """Get repository format version from CLI args or environment, defaulting to 2."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--repo-version",
        default=os.environ.get("REPO_VERSION", "2"),
        choices=["1", "2", "3"],
        help="Repository format version: 2 (default), 3 (K8s extensions), or 1 (legacy)",
    )
    args, _ = parser.parse_known_args()
    result: str = args.repo_version
    return result


def get_stage() -> str:
    """Get deployment stage from CLI args or environment, defaulting to dev."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--stage",
        default=os.environ.get("STAGE", "dev"),
        choices=["dev", "stage", "prod"],
        help="Deployment stage: dev (default), stage, or prod",
    )
    args, _ = parser.parse_known_args()
    result: str = args.stage
    return result


# Repository version determines paths and JSON format
REPO_VERSION = get_repo_version()
STAGE = get_stage()
# Map REPO_VERSION to directory name: 1 → "default", everything else → "v{N}"
GARDEN_DIR_NAME = "default" if REPO_VERSION == "1" else f"v{REPO_VERSION}"
PUBLIC_BASE_PATH = f"/garden/{GARDEN_DIR_NAME}"
# Modern formats (v2+) use "images/", v1 uses "app-garden-images/"
IMAGES_DIR_NAME = "images" if is_modern_format(REPO_VERSION) else "app-garden-images"


def ensure_public_path(asset_path: str) -> str:
    """Ensure assets resolve under the public Garden path."""
    if not asset_path:
        return asset_path

    if asset_path.startswith(("http://", "https://")):
        return asset_path

    if asset_path.startswith(PUBLIC_BASE_PATH):
        return asset_path

    # For modern formats (v2+), use relative paths (images/name.png)
    # For legacy, use absolute paths (/app-garden-images/name.png)
    if is_modern_format(REPO_VERSION):
        # Extract just the filename and use relative path
        filename = Path(asset_path).name
        return f"{IMAGES_DIR_NAME}/{filename}"
    else:
        # Legacy: absolute path under garden/default
        if asset_path.startswith("/"):
            return f"{PUBLIC_BASE_PATH}{asset_path}"
        return f"{PUBLIC_BASE_PATH}/{asset_path.lstrip('/')}"


def load_json_file(file_path: Path) -> dict[str, Any]:
    """Load and parse a JSON file."""
    try:
        with open(file_path) as f:
            result: dict[str, Any] = json.load(f)
            return result
    except json.JSONDecodeError as e:
        print(f"Error parsing {file_path}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        sys.exit(1)


def load_compose_file(compose_path: Path) -> str:
    """Load docker-compose file as a string."""
    try:
        with open(compose_path) as f:
            return f.read()
    except Exception as e:
        print(f"Error reading {compose_path}: {e}")
        return ""


def extract_docker_images(compose_content: str) -> list[str]:
    """Extract all Docker image references from docker-compose content."""
    import yaml

    images = []
    try:
        data = yaml.safe_load(compose_content)
        if data and "services" in data:
            for _service, config in data["services"].items():
                if config and "image" in config:
                    images.append(config["image"])
    except Exception as e:
        print(f"Warning: Could not extract images from compose content: {e}")

    return images


def strip_stage_suffix(tag: str) -> str:
    """Strip known stage suffixes and optional 'v' prefix from image tag.

    Removes trailing -dev or -stage suffixes and leading 'v' from version tags
    to produce a clean semver tag suitable for reapplying stage-specific suffixes.

    Examples:
        "1.0.0-dev"   -> "1.0.0"
        "v1.0.0-stage" -> "1.0.0"
        "v1.0.0"      -> "1.0.0"
        "1.0.0"       -> "1.0.0"
    """
    tag = re.sub(r"-(dev|stage)$", "", tag)
    if re.match(r"^v\d", tag):
        tag = tag[1:]
    return tag


def transform_image_tag_for_stage(image: str, stage: str) -> str:
    """Transform {IMAGE_PREFIX} image tags for the target deployment stage.

    Strips any existing stage suffixes and v-prefixes before applying the
    correct suffix for the target stage.

    Only transforms images in the {IMAGE_PREFIX} namespace.
    - dev:   {IMAGE_PREFIX}/app:1.0.0-dev
    - stage: {IMAGE_PREFIX}/app:1.0.0-stage
    - prod:  {IMAGE_PREFIX}/app:1.0.0
    """
    if not image.startswith(f"{IMAGE_PREFIX}/"):
        return image  # Don't modify external images (postgres, redis, etc.)

    if "@sha256:" in image:
        return image

    # Split image:tag
    if ":" in image:
        name, tag = image.rsplit(":", 1)
        clean_tag = strip_stage_suffix(tag)
    else:
        name = image
        clean_tag = "latest"

    if stage == "prod":
        return f"{name}:{clean_tag}"

    return f"{name}:{clean_tag}-{stage}"


def transform_env_value_for_stage(value: str, stage: str) -> str:
    """Transform image references in environment variable values.

    Handles patterns like:
    - ${VAR:-{IMAGE_PREFIX}/image:tag} -> ${VAR:-{IMAGE_PREFIX}/image:tag-stage}
    - {IMAGE_PREFIX}/image:tag -> {IMAGE_PREFIX}/image:tag-stage
    """
    import re

    if stage == "prod":
        return value

    # Pattern for ${VAR:-default} with {IMAGE_PREFIX} image
    default_pattern = rf"(\$\{{[^}}]+:-)((?:{re.escape(IMAGE_PREFIX)})/[^}}]+)(\}})"

    def replace_default(match):
        prefix = match.group(1)
        image = match.group(2)
        suffix = match.group(3)
        return prefix + transform_image_tag_for_stage(image, stage) + suffix

    transformed = re.sub(default_pattern, replace_default, value)

    # If no default pattern matched, check for bare {IMAGE_PREFIX} image
    if transformed == value and value.startswith(f"{IMAGE_PREFIX}/"):
        transformed = transform_image_tag_for_stage(value, stage)

    return transformed


def _transform_service_env_for_stage(env: dict | list, stage: str) -> None:
    """Transform {IMAGE_PREFIX} image references in service environment variables."""
    if isinstance(env, dict):
        for key, value in env.items():
            if isinstance(value, str) and f"{IMAGE_PREFIX}/" in value:
                env[key] = transform_env_value_for_stage(value, stage)
    elif isinstance(env, list):
        for i, item in enumerate(env):
            if isinstance(item, str) and f"{IMAGE_PREFIX}/" in item:
                env[i] = transform_env_value_for_stage(item, stage)


def transform_compose_for_stage(compose_content: str, stage: str) -> str:
    """Transform image tags in compose YAML content for the given stage.

    Transforms both service image fields and environment variable values
    that reference {IMAGE_PREFIX} images (e.g. sandbox/agent image refs).
    """
    import yaml

    if stage == "prod":
        return compose_content  # No transformation needed for prod

    try:
        data = yaml.safe_load(compose_content)
        if data and "services" in data:
            for _service, config in data["services"].items():
                if not config:
                    continue
                if "image" in config:
                    config["image"] = transform_image_tag_for_stage(config["image"], stage)
                if "environment" in config:
                    _transform_service_env_for_stage(config["environment"], stage)
        result: str = yaml.dump(data, default_flow_style=False, sort_keys=False)
    except Exception as e:
        print(f"Warning: Could not transform compose content for stage: {e}")
        return compose_content
    else:
        return result


def process_app(app_path: Path) -> dict[str, Any] | None:
    """Process an app directory and return its registry entry."""
    metadata_path = app_path / "kamiwaza.json"

    if not metadata_path.exists():
        print(f"Warning: No kamiwaza.json found in {app_path}")
        return None

    metadata = load_json_file(metadata_path)

    # Require docker-compose.appgarden.yml for registry artifacts
    compose_path = app_path / "docker-compose.appgarden.yml"
    if not compose_path.exists():
        print(f"Error: {app_path} is missing docker-compose.appgarden.yml (required)")
        sys.exit(1)

    compose_content = load_compose_file(compose_path)
    if not compose_content.strip():
        print(f"Error: {compose_path} is empty")
        sys.exit(1)

    # Transform image tags for the target stage
    transformed_compose = transform_compose_for_stage(compose_content, STAGE)
    metadata["compose_yml"] = transformed_compose

    # Extract Docker images from transformed compose content
    metadata["docker_images"] = extract_docker_images(transformed_compose)

    # Transform extra_docker_images tags for the target stage
    if metadata.get("extra_docker_images"):
        metadata["extra_docker_images"] = [
            transform_image_tag_for_stage(img, STAGE) for img in metadata["extra_docker_images"]
        ]

    # Remove internal fields that shouldn't be in the registry
    metadata.pop("compose_yml_file", None)
    metadata["_compose_filename"] = f"{metadata.get('name', app_path.name)}.appgarden.yml"
    metadata["_compose_content"] = compose_content

    return metadata


def process_service(service_path: Path) -> dict[str, Any] | None:
    """Process a service directory and return its registry entry."""
    metadata = process_app(service_path)
    if metadata:
        metadata.setdefault("template_type", "service")
    return metadata


def process_tool(tool_path: Path) -> dict[str, Any] | None:
    """Process a tool directory and return its registry entry."""
    metadata_path = tool_path / "kamiwaza.json"

    if not metadata_path.exists():
        print(f"Warning: No kamiwaza.json found in {tool_path}")
        return None

    metadata = load_json_file(metadata_path)

    # For tools, compose_yml might be optional if they just use image
    compose_path = tool_path / "docker-compose.appgarden.yml"
    if not compose_path.exists():
        compose_path = tool_path / "docker-compose.yml"

    if compose_path.exists():
        compose_content = load_compose_file(compose_path)
        # Transform image tags for the target stage
        transformed_compose = transform_compose_for_stage(compose_content, STAGE)
        metadata["compose_yml"] = transformed_compose
        # Extract Docker images from transformed compose content
        metadata["docker_images"] = extract_docker_images(transformed_compose)
    elif "image" in metadata:
        # Tool has a single image defined in metadata
        original_image = metadata["image"]
        transformed_image = transform_image_tag_for_stage(original_image, STAGE)
        if transformed_image != original_image:
            print(f"  Info: Normalized image tag for {tool_path.name}: {original_image} -> {transformed_image}")
        metadata["docker_images"] = [transformed_image]
        metadata["image"] = transformed_image
    else:
        print(f"Warning: Tool {tool_path} has neither docker-compose file nor image field")
        metadata["docker_images"] = []

    # Remove internal fields
    metadata.pop("compose_yml_file", None)

    return metadata


def scan_extensions(base_path: Path, extension_type: str) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    """Scan all extensions of a given type and return entries and paths."""
    extensions: list[dict[str, Any]] = []
    extension_paths: dict[str, Path] = {}
    extensions_path = base_path / extension_type

    if not extensions_path.exists():
        print(f"Warning: {extensions_path} directory not found")
        return extensions, extension_paths

    for item in sorted(extensions_path.iterdir()):
        if item.is_dir() and not item.name.startswith("."):
            print(f"Processing {extension_type}/{item.name}...")

            if extension_type == "apps":
                entry = process_app(item)
            elif extension_type == "services":
                entry = process_service(item)
            else:
                entry = process_tool(item)

            if entry:
                # Store extension directory name for image copying
                entry["_extension_name"] = item.name
                extension_paths[item.name] = item
                extensions.append(entry)

    return extensions, extension_paths


def _validate_service_template_type(entry: dict[str, Any]) -> list[str]:
    """Validate template_type for service entries."""
    errors: list[str] = []
    template_type = entry.get("template_type")
    if template_type:
        normalized = str(template_type).strip().lower()
        if normalized.endswith("s"):
            normalized = normalized[:-1]
        if normalized != "service":
            errors.append(f"{entry.get('name', 'Unknown')}: template_type must be 'service'")
    return errors


def validate_registry_entry(entry: dict[str, Any], entry_type: str) -> list[str]:
    """Validate a registry entry and return list of errors."""
    errors: list[str] = []

    # Common required fields
    required_fields = ["name", "version", "description", "source_type", "visibility"]

    if entry_type == "tool":
        # Tools need either image or compose_yml
        if "image" not in entry and "compose_yml" not in entry:
            errors.append(f"{entry.get('name', 'Unknown')}: Must have either 'image' or 'compose_yml'")
    else:
        # Apps need compose_yml
        if "compose_yml" not in entry:
            errors.append(f"{entry.get('name', 'Unknown')}: Missing 'compose_yml'")
        if entry_type == "service":
            errors.extend(_validate_service_template_type(entry))

    for field in required_fields:
        if field not in entry:
            errors.append(f"{entry.get('name', 'Unknown')}: Missing required field '{field}'")

    # Validate risk_tier
    if "risk_tier" in entry and (not isinstance(entry["risk_tier"], int) or entry["risk_tier"] not in [0, 1, 2]):
        errors.append(f"{entry.get('name', 'Unknown')}: risk_tier must be 0, 1, or 2")

    return errors


def validate_duplicate_preview_images(apps: list[dict], tools: list[dict]) -> list[str]:
    """Check for duplicate preview_image values across all extensions."""
    errors: list[str] = []
    preview_images: dict[str, Any] = {}

    for entry in apps + tools:
        preview_image = entry.get("preview_image")
        if preview_image and preview_image != "null":
            if preview_image in preview_images:
                errors.append(
                    f"Duplicate preview_image '{preview_image}' found in "
                    f"'{entry.get('name')}' and '{preview_images[preview_image]}'"
                )
            else:
                preview_images[preview_image] = entry.get("name")

    return errors


def copy_preview_images(extensions: list[dict], extension_paths: dict[str, Path], images_dir: Path) -> None:
    """Copy preview images into the appropriate images directory."""
    for entry in extensions:
        preview_image = entry.get("preview_image")
        if not preview_image or preview_image == "null":
            continue

        # Extract filename from path
        try:
            image_filename = Path(preview_image).name
        except Exception:
            print(f"Warning: Invalid preview_image path '{preview_image}' in {entry.get('name')}")
            continue

        # Get the extension's source directory
        extension_name = entry.get("_extension_name")
        if not extension_name or extension_name not in extension_paths:
            print(f"Warning: Cannot find source directory for {entry.get('name')}")
            continue

        extension_dir = extension_paths[extension_name]

        # Search for the image: full relative path, filename only, then fallbacks
        candidates = [
            extension_dir / preview_image,
            extension_dir / image_filename,
            *(extension_dir / fb for fb in ["icon.png", "logo.png", "preview.png", "icon.svg"]),
        ]
        source_image = next((p for p in candidates if p.exists()), None)

        if source_image is None:
            print(f"Warning: Preview image '{image_filename}' not found for {entry.get('name')} in {extension_dir}")
            continue

        # Copy to images directory
        dest_image = images_dir / image_filename
        try:
            shutil.copy2(source_image, dest_image)
            print(f"  Copied {source_image.name} for {entry.get('name')}")
        except Exception as e:
            print(f"Warning: Failed to copy {source_image} to {dest_image}: {e}")


def _validate_extensions(
    apps: list[dict[str, Any]],
    services: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> None:
    """Validate all registry entries, exit on errors."""
    all_errors: list[str] = []
    for app in apps:
        all_errors.extend(validate_registry_entry(app, "app"))
    for service in services:
        all_errors.extend(validate_registry_entry(service, "service"))
    for tool in tools:
        all_errors.extend(validate_registry_entry(tool, "tool"))

    preview_errors = validate_duplicate_preview_images(apps + services, tools)
    all_errors.extend(preview_errors)

    if all_errors:
        print("\nValidation errors found:")
        for error in all_errors:
            print(f"  - {error}")
        sys.exit(1)


def _clean_registry_entries(entries: list[dict[str, Any]]) -> None:
    """Remove internal fields and ensure public preview image paths."""
    for entry in entries:
        entry.pop("_compose_filename", None)
        entry.pop("_compose_content", None)
        entry.pop("_extension_name", None)
        preview_image = entry.get("preview_image")
        if preview_image and preview_image != "null":
            entry["preview_image"] = ensure_public_path(preview_image)
        if not is_modern_format(REPO_VERSION):
            entry.pop("kamiwaza_version", None)


def _copy_helper_files(script_dir: Path, registry_root: Path) -> None:
    """Copy helper files to registry root."""
    helper_files = [
        ("package-setup.sh", True),
        ("PACKAGE-README.md", False),
        ("serve-registry.py", True),
        ("kamiwaza-registry.env.template", False),
    ]
    for filename, executable in helper_files:
        src = script_dir / filename
        dst = registry_root / ("README.md" if filename == "PACKAGE-README.md" else filename)
        if src.exists():
            shutil.copy2(src, dst)
            if executable:
                dst.chmod(0o755)
            print(f"  Copied {filename}")
        else:
            print(f"  Warning: {filename} not found")


def _ensure_gitignore(repo_root: Path) -> None:
    """Add build/ to .gitignore if not present."""
    gitignore_path = repo_root / ".gitignore"
    if gitignore_path.exists():
        with open(gitignore_path) as f:
            gitignore_content = f.read()
        if "build/" not in gitignore_content:
            print("\nAdding build/ to .gitignore...")
            with open(gitignore_path, "a") as f:
                f.write("\n# Generated registry files\nbuild/\n")


def main() -> None:
    """Main entry point."""
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent

    # Clean and recreate build directory (ephemeral working directory)
    build_dir = repo_root / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    # Create registry directory structure using versioned path
    registry_root = build_dir / "kamiwaza-extension-registry"
    registry_root.mkdir(parents=True, exist_ok=True)
    garden_root = registry_root / "garden" / GARDEN_DIR_NAME
    garden_root.mkdir(parents=True, exist_ok=True)

    print(
        f"Building extension registry files"
        f" (stage: {STAGE}, repo version: {REPO_VERSION}, path: garden/{GARDEN_DIR_NAME})..."
    )
    print("=" * 50)

    # Scan extensions
    print("\nProcessing apps...")
    apps, app_paths = scan_extensions(repo_root, "apps")
    print("\nProcessing services...")
    services, service_paths = scan_extensions(repo_root, "services")
    print("\nProcessing tools...")
    tools, tool_paths = scan_extensions(repo_root, "tools")
    all_extension_paths = {**app_paths, **service_paths, **tool_paths}

    # Validate all entries
    print("\nValidating entries...")
    _validate_extensions(apps, services, tools)

    # Create images directory and copy preview images
    images_dir = garden_root / IMAGES_DIR_NAME
    images_dir.mkdir(parents=True, exist_ok=True)
    print("\nCopying preview images...")
    garden_apps = apps + services
    copy_preview_images(garden_apps + tools, all_extension_paths, images_dir)

    # Clean internal fields and write registry files
    _clean_registry_entries(garden_apps)
    _clean_registry_entries(tools)

    apps_file = garden_root / "apps.json"
    tools_file = garden_root / "tools.json"
    with open(apps_file, "w") as f:
        json.dump(garden_apps, f, indent=2)
    with open(tools_file, "w") as f:
        json.dump(tools, f, indent=2)

    print("\nSuccessfully generated:")
    print(f"  - {apps_file} ({len(apps)} apps, {len(services)} services)")
    print(f"  - {tools_file} ({len(tools)} tools)")

    # Copy helper files and ensure gitignore
    print("\nCopying helper files...")
    _copy_helper_files(script_dir, registry_root)
    _ensure_gitignore(repo_root)


if __name__ == "__main__":
    main()
