#!/usr/bin/env python3
# mypy: ignore-errors
"""
List extensions published to a remote registry stage.

Downloads the remote registry and displays apps, services, and tools
with their versions and metadata.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from lib.s3_operations import download_registry, get_bucket_for_stage


def get_garden_dir(repo_version: str) -> str:
    """Map repo version to garden directory name."""
    return "default" if repo_version == "1" else f"v{repo_version}"


def load_registry_file(path: Path) -> list:
    """Load a registry JSON file."""
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def print_extensions(entries: list, ext_type: str, emoji: str) -> None:
    """Print a formatted list of extensions."""
    if not entries:
        print(f"\n{emoji} No {ext_type} found")
        return

    # Filter by template_type if needed
    if ext_type == "services":
        entries = [e for e in entries if e.get("template_type") == "service"]
    elif ext_type == "apps":
        entries = [e for e in entries if e.get("template_type") != "service"]

    if not entries:
        print(f"\n{emoji} No {ext_type} found")
        return

    print(f"\n{emoji} {ext_type.title()} ({len(entries)}):")
    print(f"  {'Name':<35} {'Version':<12} {'Risk':<6} {'Verified'}")
    print(f"  {'-' * 35} {'-' * 12} {'-' * 6} {'-' * 8}")

    for entry in sorted(entries, key=lambda x: x.get("name", "")):
        name = entry.get("name", "unknown")
        if len(name) > 34:
            name = name[:31] + "..."
        version = entry.get("version", "?")
        risk = entry.get("risk_tier", "?")
        verified = "Yes" if entry.get("verified") else "No"
        print(f"  {name:<35} {version:<12} {risk:<6} {verified}")


def main() -> None:
    parser = argparse.ArgumentParser(description="List published extensions in remote registry")
    parser.add_argument(
        "--stage",
        default=os.environ.get("STAGE", "dev"),
        choices=["dev", "stage", "prod"],
        help="Stage to query (default: dev)",
    )
    parser.add_argument(
        "--repo-version",
        default=os.environ.get("REPO_VERSION", "2"),
        choices=["1", "2", "3"],
        help="Repository format version (default: 2)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted table",
    )
    args = parser.parse_args()

    # Get bucket and garden dir for stage
    bucket = get_bucket_for_stage(args.stage)
    garden_dir = get_garden_dir(args.repo_version)

    print(f"Fetching registry from {args.stage} (s3://{bucket}/garden/{garden_dir}/)...")

    # Download to temp directory
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        try:
            working_path, _ = download_registry(bucket, garden_dir, tmp_path, create_backup=False)
        except Exception as e:
            print(f"Error downloading registry: {e}", file=sys.stderr)
            sys.exit(1)

        # Load registry files
        apps_file = working_path / "apps.json"
        tools_file = working_path / "tools.json"

        apps = load_registry_file(apps_file)
        tools = load_registry_file(tools_file)

        if args.json:
            print(json.dumps({"apps": apps, "tools": tools}, indent=2))
            return

        # Separate apps and services
        services = [a for a in apps if a.get("template_type") == "service"]
        apps_only = [a for a in apps if a.get("template_type") != "service"]

        # Print summary
        print(f"\nRegistry: {args.stage} ({args.repo_version})")
        print(f"{'=' * 60}")

        print_extensions(apps_only, "apps", "📦")
        print_extensions(services, "services", "🔧")
        print_extensions(tools, "tools", "🛠️")

        total = len(apps_only) + len(services) + len(tools)
        print(f"\n{'=' * 60}")
        print(f"Total: {total} extensions ({len(apps_only)} apps, {len(services)} services, {len(tools)} tools)")


if __name__ == "__main__":
    main()
