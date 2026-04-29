#!/usr/bin/env python3
"""
Validate docker-compose files for App Garden compatibility.

This script checks docker-compose.appgarden.yml files to ensure they
follow App Garden requirements:
- No host port mappings
- No bind mounts
- Only named volumes
- Required extra_hosts
- Accessible images
- Resource limits defined
- No explicit container_name (platform manages naming)
- No explicit networks section (platform manages networking)
- Volume names must not use reserved infrastructure prefixes
- Volume and image names must contain the extension identifier (from kamiwaza.json)
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from image_prefix import get_image_prefix

# Reserved volume name prefixes used by Kamiwaza platform infrastructure.
# Extensions must not use these to avoid conflicts with cleanup tooling.
RESERVED_VOLUME_PREFIXES = ("kamiwaza-", "buildx_buildkit_")
IMAGE_REFERENCE_PATTERN = re.compile(
    r"^(?:[\w.-]+(?::\d+)?(?:/[\w.-]+)+(?::[\w][\w.-]*)?|[\w.-]+(?::[\w][\w.-]*)?)(?:@sha256:[a-f0-9]{64})?$"
)
IMAGE_PREFIX_PLACEHOLDER_PATTERN = re.compile(r"^(?:\$IMAGE_PREFIX|\$\{IMAGE_PREFIX(?:[:]?-[^}]+)?\})/")

# Image prefixes owned by extensions (checked for extension identifier).
# External images (postgres, redis, etc.) are excluded from naming checks.
EXTENSION_IMAGE_PREFIX = f"{get_image_prefix(script_path=__file__)}/"


def sanitize_extension_name(name: str) -> str:
    """Sanitize kamiwaza.json 'name' into a Docker-safe identifier.

    Lowercases, replaces non-alphanumeric characters with hyphens,
    collapses consecutive hyphens, and strips leading/trailing hyphens.
    """
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def load_compose_file(file_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Load and parse a docker-compose YAML file. Returns (data, error_message)."""
    try:
        with open(file_path) as f:
            return yaml.safe_load(f), None
    except yaml.YAMLError as e:
        return None, f"Invalid YAML: {e}"
    except Exception as e:
        return None, f"Error reading file: {e}"


def validate_ports(ports: list[Any], service_name: str) -> list[str]:
    """Validate port configuration."""
    errors = []

    for port in ports:
        if isinstance(port, str) and ":" in port and not port.startswith(":"):
            errors.append(
                f"Service '{service_name}': Port mapping '{port}' includes host port. Use only container port."
            )
        elif isinstance(port, dict) and "published" in port:
            errors.append(f"Service '{service_name}': Port has 'published' field (host port). Remove it.")

    return errors


def _is_bind_mount(volume: str) -> bool:
    """Check if a volume string represents a bind mount."""
    if volume.startswith("/") or volume.startswith("./") or volume.startswith("../"):
        return True
    return ":" in volume and ("/" in volume.split(":")[0] or "\\" in volume.split(":")[0])


def validate_volumes(
    volumes: list[Any],
    service_name: str,
    allowed_bind_mounts: list[str] | None = None,
) -> list[str]:
    """Validate volume configuration.

    Args:
        allowed_bind_mounts: Exact volume strings to exempt from bind mount checks.
            Configured via kamiwaza.json ``validation.allowed_bind_mounts``.
    """
    allowed = set(allowed_bind_mounts or [])
    errors = []

    for volume in volumes:
        if isinstance(volume, str):
            if volume in allowed:
                continue
            if _is_bind_mount(volume):
                errors.append(f"Service '{service_name}': Bind mount detected: '{volume}'. Only named volumes allowed.")
        elif isinstance(volume, dict) and volume.get("type") == "bind":
            errors.append(f"Service '{service_name}': Bind mount detected. Only named volumes allowed.")

    return errors


def _check_extra_hosts(service: dict[str, Any], service_name: str) -> list[str]:
    """Check if service has required extra_hosts for host.docker.internal references."""
    env_vars = service.get("environment", {})
    needs_host = False

    if isinstance(env_vars, list):
        needs_host = any(isinstance(var, str) and "host.docker.internal" in var for var in env_vars)
    elif isinstance(env_vars, dict):
        needs_host = any(value and "host.docker.internal" in str(value) for value in env_vars.values())

    if not needs_host:
        return []

    extra_hosts = service.get("extra_hosts", [])
    if not extra_hosts:
        return [f"Service '{service_name}': References host.docker.internal but missing extra_hosts"]

    if not any("host.docker.internal:host-gateway" in host for host in extra_hosts):
        return [f"Service '{service_name}': Missing 'host.docker.internal:host-gateway' in extra_hosts"]

    return []


def _check_image_format(service: dict[str, Any], service_name: str, ext_id: str | None = None) -> list[str]:
    """Validate image format and extension identifier."""
    if "image" not in service:
        return []
    image = service["image"]
    if not isinstance(image, str):
        return [f"Service '{service_name}': Image must be a string"]
    normalized_image = IMAGE_PREFIX_PLACEHOLDER_PATTERN.sub(EXTENSION_IMAGE_PREFIX, image, count=1)
    if not IMAGE_REFERENCE_PATTERN.match(normalized_image):
        return [f"Service '{service_name}': Invalid image format: '{image}'"]
    if ext_id and normalized_image.startswith(EXTENSION_IMAGE_PREFIX):
        image_without_prefix = normalized_image[len(EXTENSION_IMAGE_PREFIX) :]
        image_name = image_without_prefix.split(":")[0]  # strip tag
        if ext_id not in image_name:
            return [
                f"Service '{service_name}': Image '{image}' does not contain "
                f"extension identifier '{ext_id}'. "
                f"Expected format: {EXTENSION_IMAGE_PREFIX}{ext_id}-{{service}}:{{version}}"
            ]
    return []


def validate_service(
    service: dict[str, Any],
    service_name: str,
    ext_id: str | None = None,
    allowed_bind_mounts: list[str] | None = None,
) -> list[str]:
    """Validate a single service configuration."""
    errors = []

    # Check for explicit container_name (platform manages naming)
    if "container_name" in service:
        errors.append(
            f"Service '{service_name}': Explicit 'container_name' is not allowed. "
            "The platform manages container naming."
        )

    if "ports" in service:
        errors.extend(validate_ports(service["ports"], service_name))

    if "volumes" in service:
        errors.extend(validate_volumes(service["volumes"], service_name, allowed_bind_mounts))

    if "build" in service:
        errors.append(f"Service '{service_name}': Has 'build' section. Must use pre-built images only.")

    errors.extend(_check_extra_hosts(service, service_name))

    has_limits = (
        "deploy" in service
        and "resources" in service.get("deploy", {})
        and "limits" in service.get("deploy", {}).get("resources", {})
    )
    if not has_limits:
        errors.append(f"Service '{service_name}': Missing resource limits (deploy.resources.limits)")

    errors.extend(_check_image_format(service, service_name, ext_id))

    return errors


def _validate_volume_definitions(compose_data: dict[str, Any], ext_id: str | None = None) -> list[str]:
    """Validate top-level volume definitions."""
    errors = []
    for volume_name, volume_config in (compose_data.get("volumes") or {}).items():
        # Check for reserved infrastructure prefixes
        for prefix in RESERVED_VOLUME_PREFIXES:
            if volume_name.startswith(prefix):
                errors.append(
                    f"Volume '{volume_name}': Name uses reserved infrastructure prefix '{prefix}'. "
                    "Choose a name that does not start with a platform-reserved prefix."
                )
                break

        # Check that volume name includes the extension identifier
        if ext_id and ext_id not in volume_name:
            errors.append(
                f"Volume '{volume_name}': Name must contain extension identifier '{ext_id}'. "
                f"Example: '{ext_id}_{volume_name}' or '{ext_id}-{volume_name}'"
            )

        if not isinstance(volume_config, dict):
            continue
        driver_opts = volume_config.get("driver_opts")
        if not isinstance(driver_opts, dict):
            continue
        for opt_key, opt_value in driver_opts.items():
            if "device" in opt_key and ("/" in str(opt_value) or "\\" in str(opt_value)):
                errors.append(f"Volume '{volume_name}': driver_opts may reference host path")
    return errors


def validate_compose(
    compose_data: dict[str, Any],
    ext_id: str | None = None,
    allowed_bind_mounts: list[str] | None = None,
) -> list[str]:
    """Validate entire compose file.

    Args:
        compose_data: Parsed docker-compose YAML.
        ext_id: Sanitized extension identifier from kamiwaza.json name.
            When provided, validates that volumes and images include it.
        allowed_bind_mounts: Exact volume strings exempt from bind mount checks.
    """
    if not compose_data:
        return ["Empty compose file"]

    if "services" not in compose_data:
        return ["No 'services' section found"]

    errors = []
    for service_name, service in compose_data["services"].items():
        if not isinstance(service, dict):
            errors.append(f"Service '{service_name}': Invalid service definition")
            continue
        errors.extend(validate_service(service, service_name, ext_id, allowed_bind_mounts))

    # Check for explicit networks section (platform manages networking)
    if "networks" in compose_data:
        errors.append("Explicit 'networks' section is not allowed. The platform manages network configuration.")

    errors.extend(_validate_volume_definitions(compose_data, ext_id))
    return errors


def load_extension_config(extension_path: Path) -> tuple[str | None, list[str]]:
    """Load extension identifier and validation overrides from kamiwaza.json.

    Returns:
        (ext_id, allowed_bind_mounts) — ext_id is the sanitized name,
        allowed_bind_mounts is from ``validation.allowed_bind_mounts``.
    """
    metadata_path = extension_path / "kamiwaza.json"
    if not metadata_path.exists():
        return None, []
    try:
        with open(metadata_path) as f:
            metadata = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None, []

    ext_id = None
    name = metadata.get("name")
    if isinstance(name, str) and name:
        ext_id = sanitize_extension_name(name)

    allowed_bind_mounts: list[str] = []
    validation = metadata.get("validation")
    if isinstance(validation, dict):
        abm = validation.get("allowed_bind_mounts")
        if isinstance(abm, list):
            allowed_bind_mounts = [v for v in abm if isinstance(v, str)]

    return ext_id, allowed_bind_mounts


def check_extension(extension_path: Path, _extension_type: str) -> tuple[str, list[str]]:
    """Check a single extension's docker-compose.appgarden.yml file."""
    compose_path = extension_path / "docker-compose.appgarden.yml"

    if not compose_path.exists():
        compose_path = extension_path / "docker-compose.yml"
        if not compose_path.exists():
            return extension_path.name, ["No docker-compose file found"]

    compose_data, error = load_compose_file(compose_path)
    if error or compose_data is None:
        return extension_path.name, [error or "Failed to load compose file"]

    ext_id, allowed_bind_mounts = load_extension_config(extension_path)
    errors = validate_compose(compose_data, ext_id, allowed_bind_mounts)
    return extension_path.name, errors


def _validate_extension_dirs(repo_root: Path, ext_type: str) -> int:
    """Validate all extensions of a given type. Returns error count."""
    print(f"\nValidating {ext_type}...")
    type_path = repo_root / ext_type
    total_errors = 0
    if not type_path.exists():
        return 0

    for ext_dir in sorted(type_path.iterdir()):
        if not ext_dir.is_dir() or ext_dir.name.startswith("."):
            continue
        name, errors = check_extension(ext_dir, ext_type)
        if errors:
            print(f"\n❌ {ext_type}/{name}:")
            for error in errors:
                print(f"   - {error}")
                total_errors += 1
        else:
            print(f"✅ {ext_type}/{name}")

    return total_errors


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate docker-compose files")
    parser.add_argument("--type", choices=["app", "service", "tool"], help="Extension type")
    parser.add_argument("--name", help="Extension name")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    repo_root = script_dir.parent

    total_errors = 0

    if args.type and args.name:
        ext_path = repo_root / f"{args.type}s" / args.name
        if not ext_path.exists():
            print(f"❌ Extension not found: {args.type}s/{args.name}")
            sys.exit(1)

        print(f"Validating docker-compose for {args.type}/{args.name}...")
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
        print("Validating docker-compose files for App Garden...")
        print("=" * 50)

        for ext_type in ["apps", "services", "tools"]:
            total_errors += _validate_extension_dirs(repo_root, ext_type)

    print("\n" + "=" * 50)
    if total_errors > 0:
        print(f"❌ Validation failed with {total_errors} error(s)")
        sys.exit(1)
    else:
        print("✅ All docker-compose files are valid for App Garden!")


if __name__ == "__main__":
    main()
