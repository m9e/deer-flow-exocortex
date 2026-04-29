#!/usr/bin/env python3
"""Registry remove - Safe removal of extensions from a published registry.

This script implements a safe removal workflow for the extension registry:
1. Acquire lock on the registry bucket
2. Backup remote state
3. Download current registry
4. Find matching entries by name across apps.json and tools.json
5. Show diff (entries to remove, before/after counts)
6. Prompt for confirmation
7. Remove entries, upload, verify
8. Release lock (on success) or restore backup (on failure)

Usage:
    python scripts/registry-remove.py --stage dev --repo-version 2 --name "Kaizen v3"

Options:
    --stage         Target stage (dev/stage/prod)
    --repo-version  Registry format version (1/2/3)
    --name          Registry entry name to remove (as shown in apps.json/tools.json)
    --dry-run       Show what would happen without making changes
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add scripts directory to path for imports
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.registry_merge import load_registry_json, save_registry_json
from lib.s3_operations import (
    acquire_lock,
    download_registry,
    get_bucket_for_stage,
    get_s3_endpoint,
    lock_s3_path,
    release_lock,
    restore_backup,
    upload_registry,
    verify_upload,
)


def get_garden_dir(repo_version: str) -> str:
    """Get the garden directory name for a repo version."""
    return "default" if repo_version == "1" else f"v{repo_version}"


def find_entries_to_remove(entries: list[dict], name: str) -> tuple[list[dict], list[dict]]:
    """Partition entries into matching and remaining by name.

    Args:
        entries: List of registry entries
        name: Name to match against entry["name"]

    Returns:
        Tuple of (matching_entries, remaining_entries)
    """
    matching = []
    remaining = []
    for entry in entries:
        if entry.get("name") == name:
            matching.append(entry)
        else:
            remaining.append(entry)
    return matching, remaining


def show_removal_diff(matching: list[dict], remaining: list[dict], registry_type: str, total_before: int) -> None:
    """Print the entries being removed and before/after counts.

    Args:
        matching: Entries that will be removed
        remaining: Entries that will be kept
        registry_type: "apps" or "tools"
        total_before: Total entry count before removal
    """
    print(f"\n  {registry_type}.json:")
    print(f"    Before: {total_before} entries")
    print(f"    Removing: {len(matching)} entry(ies)")
    print(f"    After: {len(remaining)} entries")
    for entry in matching:
        version = entry.get("version", "?")
        kv = entry.get("kamiwaza_version", "")
        kv_str = f", kamiwaza_version: {kv}" if kv else ""
        print(f"    - {entry.get('name', '?')} v{version}{kv_str}")
        # Print indented JSON of each entry being removed
        indented = json.dumps(entry, indent=4)
        for line in indented.split("\n"):
            print(f"      {line}")


def confirm_removal() -> bool:
    """Prompt user to type 'yes' to confirm removal.

    Returns:
        True if user confirmed, False otherwise
    """
    try:
        response = input("\nType 'yes' to confirm removal: ")
        return response.strip().lower() == "yes"
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def print_lock_diagnostics(stage: str, bucket: str, garden_dir: str) -> None:
    """Print helpful diagnostics for registry lock issues."""
    stage_upper = stage.upper()
    endpoint = get_s3_endpoint()
    stage_profile = os.getenv(f"AWS_PROFILE_{stage_upper}")
    active_profile = os.getenv("AWS_PROFILE")

    print("\n--- Lock Diagnostics ---")
    print(f"Stage: {stage}")
    print(f"Bucket: {bucket}")
    print(f"Lock Path: {lock_s3_path(bucket, garden_dir)}")
    print(f"AWS_PROFILE_{stage_upper}: {stage_profile or '<unset>'}")
    print(f"AWS_PROFILE (active): {active_profile or '<unset>'}")
    print(f"Endpoint: {endpoint or '<default AWS S3>'}")
    print(f"Hint: make remove-publish-lock STAGE={stage}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Safe removal of extensions from published registry")
    parser.add_argument("--stage", choices=["dev", "stage", "prod"], default="dev", help="Target stage (default: dev)")
    parser.add_argument(
        "--repo-version", choices=["1", "2", "3"], default="2", help="Registry format version (default: 2)"
    )
    parser.add_argument(
        "--name", required=True, help="Registry entry name to remove (as shown in apps.json/tools.json)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")

    args = parser.parse_args()

    # Configuration
    stage = args.stage
    repo_version = args.repo_version
    garden_dir = get_garden_dir(repo_version)
    name = args.name
    dry_run = args.dry_run

    print("=== Registry Remove ===")
    print(f"Stage: {stage}")
    print(f"Repo Version: {repo_version}")
    print(f"Garden Dir: {garden_dir}")
    print(f"Name: {name}")
    print(f"Dry Run: {dry_run}")
    print()

    # Get bucket
    try:
        bucket = get_bucket_for_stage(stage)
        print(f"Bucket: {bucket}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Working directory
    work_dir = Path(tempfile.mkdtemp(prefix="registry-remove-"))
    backup_path = None
    lock_acquired = False
    had_error = False

    try:
        if dry_run:
            # Dry run: download without lock, show what would be removed
            print("\n--- [DRY RUN] Downloading Remote Registry ---")
            try:
                remote_path, _ = download_registry(bucket, garden_dir, work_dir, create_backup=False)
                print(f"Remote downloaded to: {remote_path}")
            except Exception as e:
                print(f"Could not download remote registry: {e}")
                print("(Remote may be empty)")
                sys.exit(1)

            # Load both registries
            apps_entries = load_registry_json(remote_path / "apps.json")
            tools_entries = load_registry_json(remote_path / "tools.json")

            # Find matches
            apps_matching, apps_remaining = find_entries_to_remove(apps_entries, name)
            tools_matching, tools_remaining = find_entries_to_remove(tools_entries, name)

            total_matching = len(apps_matching) + len(tools_matching)

            if total_matching == 0:
                print(f"\nNo entries found with name '{name}' in apps.json or tools.json")
                print("Available names in apps.json:")
                for entry in apps_entries:
                    print(f"  - {entry.get('name', '?')} v{entry.get('version', '?')}")
                print("Available names in tools.json:")
                for entry in tools_entries:
                    print(f"  - {entry.get('name', '?')} v{entry.get('version', '?')}")
                sys.exit(1)

            print("\n--- [DRY RUN] Removal Preview ---")
            print(f"\nFound {total_matching} entry(ies) matching '{name}':")

            if apps_matching:
                show_removal_diff(apps_matching, apps_remaining, "apps", len(apps_entries))
            if tools_matching:
                show_removal_diff(tools_matching, tools_remaining, "tools", len(tools_entries))

            print(f"\n[DRY RUN] Would remove {total_matching} entry(ies)")
            print("[DRY RUN] No changes made")
            sys.exit(0)

        # --- Live run ---

        # Step 1: Acquire lock
        print("\n--- Step 1: Acquire Lock ---")
        try:
            acquire_lock(bucket, garden_dir)
            lock_acquired = True
        except RuntimeError as e:
            print(f"Failed to acquire lock: {e}")
            print_lock_diagnostics(stage, bucket, garden_dir)
            sys.exit(1)

        # Step 2: Backup and download remote state
        print("\n--- Step 2: Backup Remote State ---")
        backup_dir = Path("build/registry-backups")
        remote_path, backup_path = download_registry(bucket, garden_dir, backup_dir, create_backup=True)
        print(f"Remote downloaded to: {remote_path}")
        if backup_path:
            print(f"Backup created at: {backup_path}")

        # Step 3: Find entries to remove
        print("\n--- Step 3: Find Entries ---")
        apps_entries = load_registry_json(remote_path / "apps.json")
        tools_entries = load_registry_json(remote_path / "tools.json")

        apps_matching, apps_remaining = find_entries_to_remove(apps_entries, name)
        tools_matching, tools_remaining = find_entries_to_remove(tools_entries, name)

        total_matching = len(apps_matching) + len(tools_matching)

        if total_matching == 0:
            print(f"\nNo entries found with name '{name}' in apps.json or tools.json")
            print("Available names in apps.json:")
            for entry in apps_entries:
                print(f"  - {entry.get('name', '?')} v{entry.get('version', '?')}")
            print("Available names in tools.json:")
            for entry in tools_entries:
                print(f"  - {entry.get('name', '?')} v{entry.get('version', '?')}")
            print("\nReleasing lock and exiting.")
            sys.exit(1)

        # Step 4: Show diff
        print("\n--- Step 4: Removal Preview ---")
        print(f"\nFound {total_matching} entry(ies) matching '{name}':")

        if apps_matching:
            show_removal_diff(apps_matching, apps_remaining, "apps", len(apps_entries))
        if tools_matching:
            show_removal_diff(tools_matching, tools_remaining, "tools", len(tools_entries))

        # Step 5: Confirm
        print("\n--- Step 5: Confirm Removal ---")
        if not confirm_removal():
            print("\nRemoval cancelled by user.")
            sys.exit(0)

        # Step 6: Build output
        print("\n--- Step 6: Build Modified Registry ---")
        output_path = work_dir / "modified" / garden_dir
        output_path.mkdir(parents=True, exist_ok=True)

        # Save modified JSON files
        if apps_matching:
            save_registry_json(output_path / "apps.json", apps_remaining)
            print(f"  apps.json: {len(apps_entries)} -> {len(apps_remaining)} entries")
        else:
            # Copy unmodified apps.json
            save_registry_json(output_path / "apps.json", apps_entries)

        if tools_matching:
            save_registry_json(output_path / "tools.json", tools_remaining)
            print(f"  tools.json: {len(tools_entries)} -> {len(tools_remaining)} entries")
        else:
            # Copy unmodified tools.json
            save_registry_json(output_path / "tools.json", tools_entries)

        # Copy images directory if present
        images_dir = "images" if repo_version != "1" else "app-garden-images"
        remote_images = remote_path / images_dir
        if remote_images.exists():
            shutil.copytree(remote_images, output_path / images_dir, dirs_exist_ok=True)

        # Step 7: Upload
        print("\n--- Step 7: Push Modified Registry ---")
        upload_registry(bucket, garden_dir, output_path, delete=True)

        # Step 8: Verify
        print("\n--- Step 8: Verify Upload ---")
        if not verify_upload(bucket, garden_dir, output_path):
            print("Verification failed! Rolling back...")
            raise RuntimeError("Upload verification failed")

        # Step 9: Release lock
        print("\n--- Step 9: Release Lock ---")
        release_lock(bucket, garden_dir)
        lock_acquired = False

        print("\n=== Removal Complete ===")
        print(f"Removed {total_matching} entry(ies) for '{name}' from {bucket}/garden/{garden_dir}/")

    except SystemExit:
        raise
    except Exception as e:
        had_error = True
        print(f"\n!!! Error: {e}")

        # Restore backup if we have one
        if backup_path and backup_path.exists():
            print("\n--- Restoring Backup ---")
            try:
                restore_backup(bucket, garden_dir, backup_path)
                print("Backup restored successfully")
            except Exception as restore_err:
                print(f"Warning: Failed to restore backup: {restore_err}")

    finally:
        if lock_acquired:
            print("\n--- Release Lock (cleanup) ---")
            release_lock(bucket, garden_dir)

        # Cleanup working directory
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

        if had_error:
            sys.exit(1)


if __name__ == "__main__":
    main()
