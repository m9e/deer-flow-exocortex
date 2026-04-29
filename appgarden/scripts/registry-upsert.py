#!/usr/bin/env python3
"""Registry upsert - Safe, version-aware registry publishing.

This script implements a safe upsert workflow for the extension registry:
1. Acquire lock on the registry bucket
2. Validate local registry
3. Backup remote state
4. Download current registry
5. Merge local with remote using version-aware logic
6. Push merged registry
7. Verify upload
8. Release lock (on success) or restore backup (on failure)

Usage:
    python scripts/registry-upsert.py --stage dev --repo-version 2

Options:
    --stage         Target stage (dev/stage/prod)
    --repo-version  Registry format version (1/2/3)
    --local-registry Path to local registry (default: build/kamiwaza-extension-registry)
    --dry-run       Show what would happen without making changes
    --force NAME    Force a specific extension (bypass version checks, dev stage only)
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

# Add scripts directory to path for imports
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.registry_merge import (
    merge_registries,
    print_merge_summary,
    validate_local_registry,
)
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


def main():
    parser = argparse.ArgumentParser(description="Safe, version-aware registry upsert")
    parser.add_argument("--stage", choices=["dev", "stage", "prod"], default="dev", help="Target stage (default: dev)")
    parser.add_argument(
        "--repo-version", choices=["1", "2", "3"], default="2", help="Registry format version (default: 2)"
    )
    parser.add_argument(
        "--local-registry",
        type=Path,
        default=Path("build/kamiwaza-extension-registry"),
        help="Path to local registry (default: build/kamiwaza-extension-registry)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    parser.add_argument(
        "--force-name",
        type=str,
        default=None,
        help="Force a specific extension by name (bypass version checks for that extension only)",
    )

    args = parser.parse_args()

    # Configuration
    stage = args.stage
    repo_version = args.repo_version
    garden_dir = get_garden_dir(repo_version)
    local_registry = args.local_registry.resolve()
    dry_run = args.dry_run
    force_name = args.force_name
    force_entries = {force_name} if force_name else None

    print("=== Registry Upsert ===")
    print(f"Stage: {stage}")
    print(f"Repo Version: {repo_version}")
    print(f"Garden Dir: {garden_dir}")
    print(f"Local Registry: {local_registry}")
    print(f"Dry Run: {dry_run}")
    if force_name:
        print(f"Force Name: {force_name} (bypassing version checks for this extension)")
    print()

    # Get bucket
    had_error = False

    try:
        bucket = get_bucket_for_stage(stage)
        print(f"Bucket: {bucket}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Working directory
    work_dir = Path(tempfile.mkdtemp(prefix="registry-upsert-"))
    backup_path = None
    lock_acquired = False
    had_error = False

    try:
        # Step 1: Validate local registry
        print("\n--- Step 1: Validate Local Registry ---")
        local_garden_path = local_registry / "garden" / garden_dir
        is_valid, errors = validate_local_registry(local_garden_path, repo_version)

        if not is_valid:
            print("Local registry validation failed:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)
        print("Local registry is valid")

        if dry_run:
            print("\n--- [DRY RUN] Downloading Remote Registry ---")
            # Download without backup to simulate merge
            try:
                remote_path, _ = download_registry(bucket, garden_dir, work_dir, create_backup=False)
                print(f"Remote downloaded to: {remote_path}")
            except Exception as e:
                print(f"Could not download remote registry: {e}")
                print("(Remote may be empty - this would be a first publish)")
                remote_path = work_dir / "empty"
                remote_path.mkdir(parents=True, exist_ok=True)

            print("\n--- [DRY RUN] Merge Simulation ---")
            output_path = work_dir / "merged" / garden_dir

            if force_entries:
                print(f"Force mode: Will bypass version checks for: {', '.join(force_entries)}")

            success, apps_result, tools_result = merge_registries(
                local_registry / "garden", remote_path, output_path, repo_version, force_entries
            )

            print_merge_summary(apps_result, tools_result)

            if not success:
                print("\n[DRY RUN] Merge would FAIL due to version conflicts")
                print("Use FORCE=1 with TYPE and NAME to bypass version checks for a specific extension")
                sys.exit(1)
            else:
                print("\n[DRY RUN] Merge would SUCCEED")

            print("\n[DRY RUN] Would proceed with:")
            print("  - Acquire lock")
            print("  - Create timestamped backup")
            print("  - Push merged registry")
            print("  - Verify upload")
            print("  - Release lock")
            sys.exit(0)

        # Step 2: Acquire lock
        print("\n--- Step 2: Acquire Lock ---")
        try:
            acquire_lock(bucket, garden_dir)
            lock_acquired = True
        except RuntimeError as e:
            print(f"Failed to acquire lock: {e}")
            print_lock_diagnostics(stage, bucket, garden_dir)
            sys.exit(1)

        # Step 3: Backup and download remote state
        print("\n--- Step 3: Backup Remote State ---")
        backup_dir = Path("build/registry-backups")
        remote_path, backup_path = download_registry(bucket, garden_dir, backup_dir, create_backup=True)
        print(f"Remote downloaded to: {remote_path}")
        if backup_path:
            print(f"Backup created at: {backup_path}")

        # Step 4: Merge registries
        print("\n--- Step 4: Merge Registries ---")
        output_path = work_dir / "merged" / garden_dir

        if force_entries:
            print(f"Force mode: Bypassing version checks for: {', '.join(force_entries)}")

        success, apps_result, tools_result = merge_registries(
            local_registry / "garden", remote_path, output_path, repo_version, force_entries
        )

        print_merge_summary(apps_result, tools_result)

        if not success:
            print("\nMerge failed! Rolling back...")
            raise RuntimeError("Merge failed due to version conflicts")

        # Step 5: Push merged registry
        print("\n--- Step 5: Push Merged Registry ---")
        upload_registry(bucket, garden_dir, output_path, delete=True)

        # Step 6: Verify upload
        print("\n--- Step 6: Verify Upload ---")
        if not verify_upload(bucket, garden_dir, output_path):
            print("Verification failed! Rolling back...")
            raise RuntimeError("Upload verification failed")

        # Step 7: Success - release lock
        print("\n--- Step 7: Release Lock ---")
        release_lock(bucket, garden_dir)
        lock_acquired = False

        print("\n=== Upsert Complete ===")
        print(f"Registry successfully updated in {bucket}/garden/{garden_dir}/")

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
            print("\n--- Step 7: Release Lock (cleanup) ---")
            release_lock(bucket, garden_dir)

        # Cleanup working directory
        import shutil

        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

        if had_error:
            sys.exit(1)


if __name__ == "__main__":
    main()
