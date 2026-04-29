#!/usr/bin/env python3
"""
Validate kamiwaza.json metadata files for all extensions.

This script checks that all extensions have valid metadata files with
required fields and correct formats.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

IMAGE_REFERENCE_PATTERN = re.compile(
    r"^(?:[\w.-]+(?::\d+)?(?:/[\w.-]+)+(?::[\w][\w.-]*)?|[\w.-]+(?::[\w][\w.-]*)?)(?:@sha256:[a-f0-9]{64})?$"
)


def load_json_file(file_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Load and parse a JSON file. Returns (data, error_message)."""
    try:
        with open(file_path) as f:
            return json.load(f), None
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    except Exception as e:
        return None, f"Error reading file: {e}"


def validate_version(version: str) -> bool:
    """Check if version follows semantic versioning."""
    pattern = r"^(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$"
    return bool(re.match(pattern, version))


def validate_kamiwaza_version(constraint: str) -> bool:
    """Check if kamiwaza_version is a valid semver constraint.

    Valid formats:
    - Single constraint: >=0.8.0, <1.0.0, ==0.8.1, ~=0.8.0
    - Multiple constraints: >=0.8.0,<1.0.0
    """
    # Pattern for a single version constraint
    single_pattern = r"^(>=|<=|>|<|==|~=|!=)\d+\.\d+\.\d+(-[0-9A-Za-z-]+)?$"

    # Split on comma and validate each part
    parts = [p.strip() for p in constraint.split(",")]
    return all(re.match(single_pattern, part) for part in parts)


def normalize_template_type(value: Any) -> str | None:
    """Normalize template_type values to app/tool/service when possible."""
    if value is None:
        return None
    raw_value = getattr(value, "value", value)
    if isinstance(raw_value, str):
        cleaned = raw_value.strip().lower()
        if cleaned in {"apps", "tools", "services"}:
            cleaned = cleaned[:-1]
        if cleaned in {"app", "tool", "service"}:
            return cleaned
    return None


def validate_image_tag(metadata: dict[str, Any]) -> list[str]:
    """Validate that image fields don't contain stage suffixes or v-prefixes.

    Checks the 'image' field in kamiwaza.json for common issues:
    - Stage suffixes (-dev, -stage) that shouldn't be in source metadata
    - Version tag with 'v' prefix (should be bare semver)
    - Version mismatch between image tag and version field
    """
    warnings: list[str] = []
    image = metadata.get("image")
    if not image or not isinstance(image, str):
        return warnings

    version = metadata.get("version", "")

    if ":" not in image:
        return warnings

    _name, tag = image.rsplit(":", 1)

    if re.search(r"-(dev|stage)$", tag):
        warnings.append(
            f"Image tag contains stage suffix: '{image}'. "
            "Remove '-dev' or '-stage' from the image field in kamiwaza.json; "
            "stage suffixes are applied automatically during build/publish."
        )

    if re.match(r"^v\d", tag):
        warnings.append(f"Image tag has 'v' prefix: '{image}'. Use bare semver (e.g., '1.0.0') without 'v' prefix.")

    # Strip stage suffix and v-prefix for version comparison
    clean_tag = re.sub(r"-(dev|stage)$", "", tag)
    if re.match(r"^v\d", clean_tag):
        clean_tag = clean_tag[1:]

    if version and clean_tag != version:
        warnings.append(f"Image tag version '{clean_tag}' does not match kamiwaza.json version '{version}'.")

    return warnings


def validate_preview_image(image_path: str, extension_path: Path) -> tuple[bool, str | None]:
    """Validate preview_image field.

    Convention: images/{name}-preview.{ext}
    Returns (is_valid, error_message).
    """
    valid_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

    if not isinstance(image_path, str):
        return False, "preview_image must be a string"

    # Already-resolved paths from platform
    if image_path.startswith("/api/app-garden-images/"):
        return True, None

    # Must start with images/
    if not image_path.startswith("images/"):
        return False, "preview_image must start with 'images/' (e.g., images/my-app-preview.png)"

    if Path(image_path).suffix.lower() not in valid_extensions:
        return False, f"preview_image must be an image file ({', '.join(sorted(valid_extensions))})"

    # Check file exists
    full_path = extension_path / image_path
    if not full_path.exists():
        return False, f"preview_image file not found: {image_path}"

    return True, None


def validate_app_metadata(
    metadata: dict[str, Any],
    app_path: Path,
    expected_template_type: str = "app",
) -> list[str]:
    """Validate app metadata and return list of errors."""
    errors = []

    # Required fields for apps
    required_fields = {
        "name": str,
        "version": str,
        "source_type": str,
        "visibility": str,
        "description": str,
        "risk_tier": int,
        "verified": bool,
    }

    # Check required fields
    for field, expected_type in required_fields.items():
        if field not in metadata:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(metadata[field], expected_type):
            errors.append(f"Field '{field}' must be of type {expected_type.__name__}")

    # Validate specific field values
    if "version" in metadata and not validate_version(metadata["version"]):
        errors.append(f"Invalid version format: {metadata['version']}")

    if "source_type" in metadata:
        allowed_sources = {"kamiwaza", "user_repo", "public"}
        if metadata["source_type"] not in allowed_sources:
            errors.append(f"source_type must be one of {sorted(allowed_sources)}, got: {metadata['source_type']}")

    if "visibility" in metadata:
        allowed_visibility = {"public", "private", "team"}
        if metadata["visibility"] not in allowed_visibility:
            errors.append(f"visibility must be one of {sorted(allowed_visibility)}, got: {metadata['visibility']}")

    if "risk_tier" in metadata:
        if not isinstance(metadata["risk_tier"], int) or metadata["risk_tier"] not in [
            0,
            1,
            2,
        ]:
            errors.append("risk_tier must be 0, 1, or 2")

    # Check for docker-compose file
    compose_appgarden = app_path / "docker-compose.appgarden.yml"
    if not compose_appgarden.exists():
        errors.append("Missing docker-compose.appgarden.yml (required for App Garden)")
    else:
        try:
            content = compose_appgarden.read_text().strip()
            if not content:
                errors.append("docker-compose.appgarden.yml is empty")
        except Exception as exc:
            errors.append(f"Failed to read docker-compose.appgarden.yml: {exc}")

    # Validate optional fields if present
    if "tags" in metadata and not isinstance(metadata["tags"], list):
        errors.append("'tags' must be a list")

    if "env_defaults" in metadata and not isinstance(metadata["env_defaults"], dict):
        errors.append("'env_defaults' must be a dictionary")

    if "required_env_vars" in metadata:
        if not isinstance(metadata["required_env_vars"], list):
            errors.append("'required_env_vars' must be a list")
        elif not all(isinstance(var, str) for var in metadata["required_env_vars"]):
            errors.append("All required_env_vars must be strings")

    # Validate preview_image if present
    if "preview_image" in metadata:
        is_valid, error = validate_preview_image(metadata["preview_image"], app_path)
        if not is_valid and error is not None:
            errors.append(error)
    elif metadata.get("name"):
        errors.append(f"Warning: No preview_image set. Consider adding images/{metadata['name']}-preview.png")

    # Validate image tag cleanliness
    image_warnings = validate_image_tag(metadata)
    for warning in image_warnings:
        errors.append(f"Warning: {warning}")

    # Validate kamiwaza_version if present
    if "kamiwaza_version" in metadata:
        if not isinstance(metadata["kamiwaza_version"], str):
            errors.append("'kamiwaza_version' must be a string")
        elif not validate_kamiwaza_version(metadata["kamiwaza_version"]):
            errors.append(
                f"Invalid kamiwaza_version format: {metadata['kamiwaza_version']} "
                "(expected format like '>=0.8.0' or '>=0.8.0,<1.0.0')"
            )

    if "strip_path_prefix" in metadata:
        if not isinstance(metadata["strip_path_prefix"], bool):
            errors.append("'strip_path_prefix' must be a boolean")

    if "template_type" in metadata:
        normalized = normalize_template_type(metadata["template_type"])
        if normalized != expected_template_type:
            errors.append(f"template_type must be '{expected_template_type}' for {expected_template_type}s")

    return errors


def validate_service_metadata(metadata: dict[str, Any], service_path: Path) -> list[str]:
    """Validate service metadata and return list of errors."""
    errors = validate_app_metadata(metadata, service_path, expected_template_type="service")

    if "name" in metadata and isinstance(metadata["name"], str):
        if not metadata["name"].startswith("service-"):
            errors.append(
                f"Service name must start with 'service-' prefix. Got: '{metadata['name']}' "
                f"(should be 'service-{metadata['name']}')"
            )

    return errors


def validate_tool_metadata(metadata: dict[str, Any], tool_path: Path) -> list[str]:
    """Validate tool metadata and return list of errors."""
    errors = []

    # Required fields for tools
    required_fields = {
        "name": str,
        "version": str,
        "source_type": str,
        "visibility": str,
        "description": str,
        "risk_tier": int,
        "verified": bool,
    }

    # Check required fields
    for field, expected_type in required_fields.items():
        if field not in metadata:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(metadata[field], expected_type):
            errors.append(f"Field '{field}' must be of type {expected_type.__name__}")

    # Validate tool naming convention (must start with "tool-" or "mcp-")
    if "name" in metadata and isinstance(metadata["name"], str):
        if not metadata["name"].startswith(("tool-", "mcp-")):
            errors.append(
                f"Tool name must start with 'tool-' or 'mcp-' prefix. Got: '{metadata['name']}' "
                f"(should be 'tool-{metadata['name']}')"
            )

    # Tools should have either 'image' or docker-compose
    compose_appgarden = tool_path / "docker-compose.appgarden.yml"
    compose_dev = tool_path / "docker-compose.yml"
    has_compose = compose_appgarden.exists() or compose_dev.exists()

    if "image" not in metadata and not has_compose:
        errors.append("Tool must have either 'image' field or docker-compose file")

    # Validate specific field values
    if "version" in metadata and not validate_version(metadata["version"]):
        errors.append(f"Invalid version format: {metadata['version']}")

    # Validate tool-specific fields
    if "capabilities" in metadata:
        if not isinstance(metadata["capabilities"], list):
            errors.append("'capabilities' must be a list")
        elif not all(isinstance(cap, str) for cap in metadata["capabilities"]):
            errors.append("All capabilities must be strings")

    if "required_env_vars" in metadata:
        if not isinstance(metadata["required_env_vars"], list):
            errors.append("'required_env_vars' must be a list")
        elif not all(isinstance(var, str) for var in metadata["required_env_vars"]):
            errors.append("All required_env_vars must be strings")

    # Validate image format if present
    if "image" in metadata:
        image = metadata["image"]
        if not isinstance(image, str):
            errors.append("'image' must be a string")
        elif not IMAGE_REFERENCE_PATTERN.match(image):
            errors.append(f"Invalid image format: {image}")

    # Validate preview_image if present
    if "preview_image" in metadata:
        is_valid, error = validate_preview_image(metadata["preview_image"], tool_path)
        if not is_valid and error is not None:
            errors.append(error)
    elif metadata.get("name"):
        errors.append(f"Warning: No preview_image set. Consider adding images/{metadata['name']}-preview.png")

    # Validate image tag cleanliness
    image_warnings = validate_image_tag(metadata)
    for warning in image_warnings:
        errors.append(f"Warning: {warning}")

    # Validate kamiwaza_version if present
    if "kamiwaza_version" in metadata:
        if not isinstance(metadata["kamiwaza_version"], str):
            errors.append("'kamiwaza_version' must be a string")
        elif not validate_kamiwaza_version(metadata["kamiwaza_version"]):
            errors.append(
                f"Invalid kamiwaza_version format: {metadata['kamiwaza_version']} "
                "(expected format like '>=0.8.0' or '>=0.8.0,<1.0.0')"
            )

    if "template_type" in metadata:
        normalized = normalize_template_type(metadata["template_type"])
        if normalized != "tool":
            errors.append("template_type must be 'tool' for tools")

    return errors


def check_extension(extension_path: Path, extension_type: str) -> tuple[str, list[str]]:
    """Check a single extension and return (name, errors)."""
    metadata_path = extension_path / "kamiwaza.json"

    if not metadata_path.exists():
        return extension_path.name, ["No kamiwaza.json file found"]

    metadata, error = load_json_file(metadata_path)
    if error or metadata is None:
        return extension_path.name, [error or "Failed to load metadata"]

    if extension_type == "apps":
        errors = validate_app_metadata(metadata, extension_path)
    elif extension_type == "services":
        errors = validate_service_metadata(metadata, extension_path)
    else:
        errors = validate_tool_metadata(metadata, extension_path)

    return extension_path.name, errors


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate extension metadata")
    parser.add_argument("--type", choices=["app", "service", "tool"], help="Extension type")
    parser.add_argument("--name", help="Extension name")
    args = parser.parse_args()

    # Get the repository root
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent

    total_errors = 0

    # If specific extension requested
    if args.type and args.name:
        ext_path = repo_root / f"{args.type}s" / args.name
        if not ext_path.exists():
            print(f"❌ Extension not found: {args.type}s/{args.name}")
            sys.exit(1)

        print(f"Validating {args.type}/{args.name}...")
        print("=" * 50)

        name, errors = check_extension(ext_path, f"{args.type}s")
        if errors:
            print(f"\n❌ {args.type}s/{name}:")
            for error in errors:
                print(f"   - {error}")
            total_errors += len(errors)
        else:
            print(f"✅ {args.type}s/{name}")
    else:
        # Validate all extensions
        print("Validating extension metadata...")
        print("=" * 50)

        # Check apps
        print("\nValidating apps...")
        apps_path = repo_root / "apps"
        if apps_path.exists():
            for app_dir in sorted(apps_path.iterdir()):
                if app_dir.is_dir() and not app_dir.name.startswith("."):
                    name, errors = check_extension(app_dir, "apps")
                    if errors:
                        print(f"\n❌ apps/{name}:")
                        for error in errors:
                            print(f"   - {error}")
                            total_errors += 1
                    else:
                        print(f"✅ apps/{name}")

        # Check services
        print("\nValidating services...")
        services_path = repo_root / "services"
        if services_path.exists():
            for service_dir in sorted(services_path.iterdir()):
                if service_dir.is_dir() and not service_dir.name.startswith("."):
                    name, errors = check_extension(service_dir, "services")
                    if errors:
                        print(f"\n❌ services/{name}:")
                        for error in errors:
                            print(f"   - {error}")
                            total_errors += 1
                    else:
                        print(f"✅ services/{name}")

        # Check tools
        print("\nValidating tools...")
        tools_path = repo_root / "tools"
        if tools_path.exists():
            for tool_dir in sorted(tools_path.iterdir()):
                if tool_dir.is_dir() and not tool_dir.name.startswith("."):
                    name, errors = check_extension(tool_dir, "tools")
                    if errors:
                        print(f"\n❌ tools/{name}:")
                        for error in errors:
                            print(f"   - {error}")
                            total_errors += 1
                    else:
                        print(f"✅ tools/{name}")

    # Summary
    print("\n" + "=" * 50)
    if total_errors > 0:
        print(f"❌ Validation failed with {total_errors} error(s)")
        sys.exit(1)
    else:
        print("✅ All metadata files are valid!")


if __name__ == "__main__":
    main()
