#!/usr/bin/env python3
"""Show registry entry for a specific app, service, or tool."""

import argparse
import json
import os
import sys
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parents[1] / "build"


def get_garden_dir_name(repo_version: str) -> str:
    """Map REPO_VERSION to directory name: 1 → 'default', N → 'v{N}'."""
    return "default" if repo_version == "1" else f"v{repo_version}"


def get_registry_root(repo_version: str | None = None) -> tuple[Path, str]:
    """Get the registry root path for the specified repo version.

    If repo_version is None, auto-detect by checking v2 first, then default (v1).
    Returns tuple of (path, detected_repo_version).
    """
    base = BUILD_DIR / "kamiwaza-extension-registry" / "garden"

    if repo_version:
        dir_name = get_garden_dir_name(repo_version)
        return base / dir_name, repo_version

    # Auto-detect: check v2 first (default), then default (legacy)
    v2_path = base / "v2"
    if (v2_path / "apps.json").exists() or (v2_path / "tools.json").exists():
        return v2_path, "2"

    default_path = base / "default"
    if (default_path / "apps.json").exists() or (default_path / "tools.json").exists():
        return default_path, "1"

    # Fallback to v2 (the default)
    return v2_path, "2"


def main() -> None:
    parser = argparse.ArgumentParser(description="Show registry entry for a specific extension")
    parser.add_argument("type", choices=["app", "service", "tool"], help="Extension type")
    parser.add_argument("name", help="Extension name")
    parser.add_argument(
        "--repo-version",
        default=os.environ.get("REPO_VERSION"),
        help="Repository format version (1, 2, or 3). Auto-detects if not specified.",
    )
    args = parser.parse_args()

    ext_type = args.type
    name = args.name
    registry_root, _detected_version = get_registry_root(args.repo_version)

    # Determine the file to read
    if ext_type in {"app", "service"}:
        registry_file = registry_root / "apps.json"
    else:
        registry_file = registry_root / "tools.json"

    # Check if file exists
    if not registry_file.exists():
        print(f"Error: {registry_file} not found. Run 'make build-registry' first.")
        sys.exit(1)

    # Load and search for entry
    try:
        with open(registry_file) as f:
            data = json.load(f)

        # Find matching entry
        entries = [e for e in data if e["name"] == name]

        if not entries:
            print(f"Error: No entry found for '{name}' in {registry_file}")
            sys.exit(1)

        # Print the entry
        version_info = registry_root.name
        print(f"=== Registry entry for {ext_type}/{name} (garden/{version_info}) ===")
        print(json.dumps(entries[0], indent=2))

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {registry_file}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
