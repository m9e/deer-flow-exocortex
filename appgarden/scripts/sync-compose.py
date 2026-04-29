#!/usr/bin/env python3
# mypy: ignore-errors
"""
Sync docker-compose files for App Garden compatibility.

This script transforms local development docker-compose.yml files into
App Garden-compatible versions by:
- Removing host port mappings
- Adding extra_hosts for Kamiwaza access
- Removing bind mounts
- Adding resource limits
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from image_prefix import get_image_prefix

IMAGE_PREFIX = get_image_prefix(script_path=__file__)


# Custom YAML literal string class for forcing block style
class LiteralString(str):
    """String subclass that will be represented as a YAML literal block scalar."""

    pass


def literal_str_representer(dumper: yaml.Dumper, data: LiteralString) -> yaml.ScalarNode:
    """Represent LiteralString as a YAML literal block scalar."""
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


# Create custom dumper
class MultilineDumper(yaml.SafeDumper):
    pass


MultilineDumper.add_representer(LiteralString, literal_str_representer)


def convert_multiline_strings(obj: Any) -> Any:
    """Recursively convert multiline strings to LiteralString for proper YAML formatting."""
    if isinstance(obj, dict):
        return {k: convert_multiline_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_multiline_strings(item) for item in obj]
    elif isinstance(obj, str) and "\n" in obj:
        return LiteralString(obj)
    return obj


def escape_dollar_signs(text: str) -> str:
    """Escape $ as $$ for docker-compose variable interpolation.

    In docker-compose, $VAR is interpolated as an environment variable.
    To use a literal $, you need to escape it as $$.
    This is important for nginx configs that use $host, $remote_addr, etc.
    """
    import re

    # Escape $ that is followed by a letter or underscore (variable names)
    # But don't double-escape already escaped $$
    result = re.sub(r"\$(?!\$)([a-zA-Z_])", r"$$\1", text)
    return result


def convert_command_to_array(command: str | list) -> list:
    """Convert a shell command string to array format for cleaner YAML output.

    Converts 'sh -c "script..."' to ['sh', '-c', 'script...']
    This avoids YAML escaping issues with complex shell scripts.
    Also escapes $ as $$ for docker-compose variable interpolation.
    """
    if isinstance(command, list):
        return command

    if isinstance(command, str):
        # Check if it's an 'sh -c' style command
        if command.startswith("sh -c "):
            # Extract the script after 'sh -c '
            script = command[6:].strip()
            # Remove surrounding quotes if present
            if (script.startswith('"') and script.endswith('"')) or (script.startswith("'") and script.endswith("'")):
                script = script[1:-1]
            # Escape $ for docker-compose
            script = escape_dollar_signs(script)
            return ["sh", "-c", script]
        elif command.startswith("bash -c "):
            script = command[8:].strip()
            if (script.startswith('"') and script.endswith('"')) or (script.startswith("'") and script.endswith("'")):
                script = script[1:-1]
            # Escape $ for docker-compose
            script = escape_dollar_signs(script)
            return ["bash", "-c", script]

    return command


def get_extension_version(extension_path: Path) -> str | None:
    """Read version from kamiwaza.json."""
    kamiwaza_json = extension_path / "kamiwaza.json"
    if kamiwaza_json.exists():
        try:
            with open(kamiwaza_json) as f:
                data = json.load(f)
                return data.get("version")
        except Exception:
            return None
    return None


def is_extension_image(image_string: str) -> bool:
    """Check if image belongs to this extension (vs external like postgres)."""
    image_name, _ = split_image_tag(image_string)
    pattern = rf"^(?:{re.escape(IMAGE_PREFIX)}|\$IMAGE_PREFIX|\$\{{IMAGE_PREFIX(?:[:]?-[^}}]+)?\}})/"
    return bool(re.match(pattern, image_name))


def split_image_tag(image_string: str) -> tuple[str, str | None]:
    """Split Docker image reference into name and tag.

    Uses the last ':' after the last '/' as tag separator to preserve:
    - Registry ports (e.g., registry:5000/image:tag)
    - Compose placeholders (e.g., ${IMAGE_PREFIX:-ghcr.io/acme/my-repo/images}/image:tag)
    """
    last_slash = image_string.rfind("/")
    last_colon = image_string.rfind(":")
    if last_colon > last_slash:
        return image_string[:last_colon], image_string[last_colon + 1 :]
    return image_string, None


def update_image_tag(image_string: str, version: str) -> str:
    """Update image tag to use version from kamiwaza.json."""
    # Defensive: strip 'v' prefix from version if present
    if version.startswith("v") and len(version) > 1 and version[1].isdigit():
        version = version[1:]

    image_name, _old_tag = split_image_tag(image_string)
    return f"{image_name}:{version}"


def load_compose_file(file_path: Path) -> dict[str, Any]:
    """Load and parse a docker-compose YAML file."""
    try:
        with open(file_path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        sys.exit(1)


def transform_ports(ports: list[Any]) -> list[str]:
    """Transform port mappings for App Garden."""
    transformed = []
    for port in ports:
        if isinstance(port, str):
            # Remove host port mapping (e.g., "3000:3000" -> "3000")
            if ":" in port:
                container_port = port.split(":")[-1]
                transformed.append(container_port)
            else:
                transformed.append(port)
        elif isinstance(port, int):
            transformed.append(str(port))
    return transformed


def transform_volumes(volumes: list[Any]) -> list[str]:
    """Remove bind mounts, keep only named volumes.

    Named volumes: volume-name or volume-name:/path/in/container
    Bind mounts: /host/path:/container/path or ./host/path:/container/path
    """
    transformed = []
    for volume in volumes:
        if isinstance(volume, str):
            # Check for bind mounts (path starts with / or ./)
            if volume.startswith("/") or volume.startswith("./"):
                # Skip bind mounts
                continue
            elif ":" in volume:
                # Could be named volume with mount path: volume-name:/container/path
                # or bind mount: /host:/container or ./host:/container
                parts = volume.split(":", 1)
                host_part = parts[0]
                if host_part.startswith("/") or host_part.startswith("./"):
                    # Bind mount - skip
                    continue
                else:
                    # Named volume with mount path - keep it
                    transformed.append(volume)
            else:
                # Just a volume name
                transformed.append(volume)
    return transformed


def add_kamiwaza_extras(service: dict[str, Any]) -> None:
    """Add Kamiwaza-specific configuration to a service."""
    # Add extra_hosts if not present
    if "extra_hosts" not in service:
        service["extra_hosts"] = []

    host_entry = "host.docker.internal:host-gateway"
    if host_entry not in service["extra_hosts"]:
        service["extra_hosts"].append(host_entry)

    # Add resource limits if not present
    if "deploy" not in service:
        service["deploy"] = {}

    if "resources" not in service["deploy"]:
        service["deploy"]["resources"] = {}

    if "limits" not in service["deploy"]["resources"]:
        # Set reasonable defaults based on service type
        service_name = service.get("image", "").lower()
        if "postgres" in service_name or "mysql" in service_name:
            limits = {"cpus": "0.5", "memory": "512M"}
        elif "redis" in service_name:
            limits = {"cpus": "0.25", "memory": "256M"}
        elif "frontend" in service_name or "nginx" in service_name:
            limits = {"cpus": "0.5", "memory": "512M"}
        else:
            limits = {"cpus": "1.0", "memory": "1G"}

        service["deploy"]["resources"]["limits"] = limits


def transform_service(
    service: dict[str, Any],
    service_name: str,
    version: str | None = None,
    extension_name: str | None = None,
) -> dict[str, Any]:
    """Transform a single service for App Garden compatibility."""
    transformed = service.copy()

    # Transform command to array format if it's a multiline shell command
    # This produces cleaner YAML output and avoids escaping issues
    if "command" in transformed and isinstance(transformed["command"], str):
        if "\n" in transformed["command"]:
            transformed["command"] = convert_command_to_array(transformed["command"])

    # Transform ports
    if "ports" in transformed:
        transformed["ports"] = transform_ports(transformed["ports"])

    # Transform volumes
    if "volumes" in transformed:
        transformed["volumes"] = transform_volumes(transformed["volumes"])
        if not transformed["volumes"]:
            # Remove empty volumes list
            del transformed["volumes"]

    # Remove build context and add image if needed
    if "build" in transformed:
        had_build = True
        del transformed["build"]

        # If no image field exists, construct one from extension and service name
        if "image" not in transformed and version and extension_name:
            constructed_image = f"{IMAGE_PREFIX}/{extension_name}-{service_name}:{version}"
            transformed["image"] = constructed_image
            print(f"  Info: Added image '{constructed_image}' for {service_name}")
        elif "image" not in transformed:
            print(f"  Warning: Removed 'build' from {service_name} - must add image field manually")
    else:
        had_build = False

    # Update image tag with version from kamiwaza.json
    if "image" in transformed and version:
        image_str = transformed["image"]
        if is_extension_image(image_str):
            transformed["image"] = update_image_tag(image_str, version)
            if not had_build:
                print(f"  Info: Updated image tag for {service_name} to {version}")

    # Add Kamiwaza extras
    add_kamiwaza_extras(transformed)

    return transformed


def transform_compose(
    compose_data: dict[str, Any],
    version: str | None = None,
    extension_name: str | None = None,
) -> dict[str, Any]:
    """Transform entire compose file for App Garden."""
    transformed = compose_data.copy()

    # Transform each service
    if "services" in transformed:
        for service_name, service in transformed["services"].items():
            transformed["services"][service_name] = transform_service(service, service_name, version, extension_name)

    # Keep only named volumes
    if "volumes" in transformed:
        # Filter out any volume configurations that might cause issues
        named_volumes = {}
        for volume_name, volume_config in transformed["volumes"].items():
            if volume_config is None:
                named_volumes[volume_name] = None
            elif isinstance(volume_config, dict):
                # Remove any driver_opts that might reference host paths
                filtered_config = {k: v for k, v in volume_config.items() if k != "driver_opts"}
                named_volumes[volume_name] = filtered_config if filtered_config else None
        transformed["volumes"] = named_volumes

    return transformed


def check_mode(
    original_path: Path,
    transformed_path: Path,
    version: str | None = None,
    extension_name: str | None = None,
) -> bool:
    """Check if transformation is needed."""
    if not transformed_path.exists():
        return True

    original = load_compose_file(original_path)
    current = load_compose_file(transformed_path)

    # Transform original and compare
    expected = transform_compose(original, version, extension_name)

    return expected != current


def sync_extension(extension_path: Path, check_only: bool = False) -> bool:
    """Sync docker-compose files for a single extension. Returns True if changes were made."""
    original_path = extension_path / "docker-compose.yml"
    transformed_path = extension_path / "docker-compose.appgarden.yml"

    if not original_path.exists():
        print(f"  No docker-compose.yml found in {extension_path}")
        return False

    # Get version from kamiwaza.json and extension name from path
    version = get_extension_version(extension_path)
    extension_name = extension_path.name

    if check_only:
        needs_update = check_mode(original_path, transformed_path, version, extension_name)
        if needs_update:
            print(f"  ⚠️  {extension_path.name} needs update")
        else:
            print(f"  ✅ {extension_path.name} is up to date")
        return needs_update

    # Load and transform with version and extension name
    original = load_compose_file(original_path)
    transformed = transform_compose(original, version, extension_name)

    # Convert multiline strings to LiteralString for proper YAML block scalar formatting
    transformed = convert_multiline_strings(transformed)

    # Write transformed file with custom dumper to preserve multiline strings
    with open(transformed_path, "w") as f:
        yaml.dump(transformed, f, Dumper=MultilineDumper, default_flow_style=False, sort_keys=False)

    print(f"  ✅ Generated {transformed_path}")
    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Sync docker-compose files for App Garden")
    parser.add_argument("--all", action="store_true", help="Process all extensions")
    parser.add_argument("--type", choices=["app", "service", "tool"], help="Extension type")
    parser.add_argument("--name", help="Extension name")
    parser.add_argument("--check", action="store_true", help="Check mode - report what would change")

    args = parser.parse_args()

    # Get the repository root
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent

    extensions_to_process = []

    if args.all:
        # Process all extensions
        for app_dir in (repo_root / "apps").iterdir():
            if app_dir.is_dir() and not app_dir.name.startswith("."):
                extensions_to_process.append(("app", app_dir))

        for service_dir in (repo_root / "services").iterdir():
            if service_dir.is_dir() and not service_dir.name.startswith("."):
                extensions_to_process.append(("service", service_dir))

        for tool_dir in (repo_root / "tools").iterdir():
            if tool_dir.is_dir() and not tool_dir.name.startswith("."):
                extensions_to_process.append(("tool", tool_dir))

    elif args.type and args.name:
        # Process specific extension
        extension_path = repo_root / f"{args.type}s" / args.name
        if extension_path.exists():
            extensions_to_process.append((args.type, extension_path))
        else:
            print(f"Error: Extension not found: {extension_path}")
            sys.exit(1)

    else:
        parser.print_help()
        sys.exit(1)

    # Process extensions
    print("Syncing docker-compose files for App Garden...")
    print("=" * 50)

    changes_made = 0
    for ext_type, ext_path in extensions_to_process:
        print(f"\n{ext_type}s/{ext_path.name}:")
        if sync_extension(ext_path, check_only=args.check):
            changes_made += 1

    # Summary
    print("\n" + "=" * 50)
    if args.check:
        if changes_made > 0:
            print(f"⚠️  {changes_made} extension(s) need updates")
            sys.exit(1)
        else:
            print("✅ All extensions are up to date")
    else:
        print(f"✅ Processed {len(extensions_to_process)} extension(s)")
        if changes_made > 0:
            print(f"   Generated {changes_made} docker-compose.appgarden.yml file(s)")


if __name__ == "__main__":
    main()
