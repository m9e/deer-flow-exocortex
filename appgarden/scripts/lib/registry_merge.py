"""Registry merge logic for upsert operations.

Provides functions to merge local registry entries with remote registry,
following version-aware upsert rules.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .version_compare import (
    ConstraintRelationship,
    VersionComparison,
    compare_constraints,
    compare_versions,
    validate_constraint,
    validate_version,
)


class UpsertAction(Enum):
    """Action to take for an upsert operation."""

    INSERT = "insert"  # Add new entry
    REPLACE = "replace"  # Replace existing entry
    FAIL = "fail"  # Operation not allowed


@dataclass
class UpsertResult:
    """Result of an upsert operation for a single entry."""

    name: str
    action: UpsertAction
    reason: str
    new_entry: dict
    replaced_entries: list[dict] = field(default_factory=list)
    error: str | None = None


@dataclass
class MergeResult:
    """Result of merging local and remote registries."""

    success: bool
    merged_entries: list[dict]
    actions: list[UpsertResult]
    errors: list[str]


def load_registry_json(path: Path) -> list[dict]:
    """Load a registry JSON file.

    Args:
        path: Path to apps.json or tools.json

    Returns:
        List of registry entries
    """
    if not path.exists():
        return []

    with open(path) as f:
        data = json.load(f)

    # Handle both array and object formats
    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and "entries" in data:
        return data["entries"]
    else:
        return []


def save_registry_json(path: Path, entries: list[dict]) -> None:
    """Save registry entries to a JSON file.

    Args:
        path: Path to save to
        entries: List of registry entries
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)


def validate_local_registry(local_path: Path, garden_version: str) -> tuple[bool, list[str]]:
    """Validate that local registry exists and is well-formed.

    Args:
        local_path: Path to local registry directory
        garden_version: Garden version (v1 or v2)

    Returns:
        Tuple of (is_valid, list of errors)
    """
    errors = []

    # Check directory exists
    if not local_path.exists():
        errors.append(f"Local registry path does not exist: {local_path}")
        return False, errors

    if not local_path.is_dir():
        errors.append(f"Local registry path is not a directory: {local_path}")
        return False, errors

    # Check for apps.json or tools.json
    apps_path = local_path / "apps.json"
    tools_path = local_path / "tools.json"

    if not apps_path.exists() and not tools_path.exists():
        errors.append(f"No apps.json or tools.json found in {local_path}")
        return False, errors

    # Validate JSON files
    for json_path in [apps_path, tools_path]:
        if json_path.exists():
            try:
                entries = load_registry_json(json_path)
                if not isinstance(entries, list):
                    errors.append(f"Invalid format in {json_path}: expected array")
                    continue

                # Validate entries
                for i, entry in enumerate(entries):
                    entry_errors = validate_entry(entry, garden_version)
                    for err in entry_errors:
                        errors.append(f"{json_path.name}[{i}]: {err}")

            except json.JSONDecodeError as e:
                errors.append(f"Invalid JSON in {json_path}: {e}")

    return len(errors) == 0, errors


def validate_entry(entry: dict, garden_version: str) -> list[str]:
    """Validate a single registry entry.

    Args:
        entry: Registry entry dict
        garden_version: Garden version (v1 or v2)

    Returns:
        List of validation errors
    """
    errors = []

    # Required fields
    required = ["name", "version"]
    for field_name in required:
        if field_name not in entry:
            errors.append(f"Missing required field: {field_name}")

    # Validate version format
    if "version" in entry:
        is_valid, err = validate_version(entry["version"])
        if not is_valid:
            errors.append(f"Invalid version: {err}")

    # Modern format (2+) requires kamiwaza_version
    if garden_version != "1":
        if "kamiwaza_version" not in entry or not entry["kamiwaza_version"]:
            errors.append("Modern registry format requires kamiwaza_version field")
        else:
            is_valid, err = validate_constraint(entry["kamiwaza_version"])
            if not is_valid:
                errors.append(f"Invalid kamiwaza_version: {err}")

    return errors


def determine_upsert_action_v1(new_entry: dict, existing_entries: list[dict]) -> UpsertResult:
    """Determine upsert action for v1 (garden/default) registry.

    v1 logic: Simple version-based replacement (immutable versions).

    Args:
        new_entry: Entry to upsert
        existing_entries: List of existing entries with same name

    Returns:
        UpsertResult with action and details
    """
    name = new_entry["name"]
    new_version = new_entry["version"]

    # No existing entry - INSERT
    if not existing_entries:
        return UpsertResult(
            name=name,
            action=UpsertAction.INSERT,
            reason="New extension",
            new_entry=new_entry,
        )

    # Should only be one entry per name in v1
    existing = existing_entries[0]
    existing_version = existing["version"]

    comparison = compare_versions(new_version, existing_version)

    if comparison == VersionComparison.NEWER:
        return UpsertResult(
            name=name,
            action=UpsertAction.REPLACE,
            reason=f"Version upgrade: {existing_version} -> {new_version}",
            new_entry=new_entry,
            replaced_entries=[existing],
        )
    elif comparison == VersionComparison.SAME:
        return UpsertResult(
            name=name,
            action=UpsertAction.FAIL,
            reason=f"Version {new_version} already exists (immutable)",
            new_entry=new_entry,
            error=f"Cannot mutate existing version {new_version}",
        )
    else:  # OLDER
        return UpsertResult(
            name=name,
            action=UpsertAction.FAIL,
            reason=f"Cannot downgrade: {existing_version} -> {new_version}",
            new_entry=new_entry,
            error=f"Cannot downgrade from {existing_version} to {new_version}",
        )


def determine_upsert_action_v2(new_entry: dict, existing_entries: list[dict]) -> UpsertResult:
    """Determine upsert action for v2 registry.

    v2 logic: Version-aware with kamiwaza_version constraints.

    Args:
        new_entry: Entry to upsert
        existing_entries: List of existing entries with same name

    Returns:
        UpsertResult with action and details
    """
    name = new_entry["name"]
    new_version = new_entry["version"]
    new_constraint = new_entry.get("kamiwaza_version")

    # Validate new entry has kamiwaza_version
    if not new_constraint:
        return UpsertResult(
            name=name,
            action=UpsertAction.FAIL,
            reason="Missing kamiwaza_version",
            new_entry=new_entry,
            error="v2 registry requires kamiwaza_version field",
        )

    # No existing entries - INSERT
    if not existing_entries:
        return UpsertResult(
            name=name,
            action=UpsertAction.INSERT,
            reason="New extension",
            new_entry=new_entry,
        )

    # Check against each existing entry
    entries_to_replace = []
    for existing in existing_entries:
        existing_constraint = existing.get("kamiwaza_version")
        existing_version = existing["version"]

        # Handle existing entry without kamiwaza_version (legacy/invalid)
        if not existing_constraint:
            return UpsertResult(
                name=name,
                action=UpsertAction.FAIL,
                reason="Existing entry missing kamiwaza_version",
                new_entry=new_entry,
                error=f"Existing entry for {name} is malformed (no kamiwaza_version)",
            )

        # Compare constraints
        relationship = compare_constraints(new_constraint, existing_constraint)

        if relationship == ConstraintRelationship.DISJOINT:
            # No overlap - can coexist, continue checking others
            continue

        elif relationship == ConstraintRelationship.SAME:
            # Same constraint - compare versions
            version_cmp = compare_versions(new_version, existing_version)

            if version_cmp == VersionComparison.NEWER:
                entries_to_replace.append(existing)
            elif version_cmp == VersionComparison.SAME:
                return UpsertResult(
                    name=name,
                    action=UpsertAction.FAIL,
                    reason=f"Version {new_version} with constraint {new_constraint} already exists",
                    new_entry=new_entry,
                    error=f"Cannot mutate existing version {new_version}",
                )
            else:  # OLDER
                return UpsertResult(
                    name=name,
                    action=UpsertAction.FAIL,
                    reason=f"Cannot downgrade: {existing_version} -> {new_version}",
                    new_entry=new_entry,
                    error=f"Cannot downgrade from {existing_version} to {new_version}",
                )

        elif relationship == ConstraintRelationship.SUPERSET:
            # New covers more versions than existing - REPLACE
            entries_to_replace.append(existing)

        elif relationship == ConstraintRelationship.SUBSET:
            # Existing covers more versions - FAIL
            return UpsertResult(
                name=name,
                action=UpsertAction.FAIL,
                reason=f"Would narrow support: {existing_constraint} -> {new_constraint}",
                new_entry=new_entry,
                error=f"Cannot narrow kamiwaza_version from {existing_constraint} to {new_constraint}",
            )

        elif relationship == ConstraintRelationship.PARTIAL:
            # Partial overlap - ambiguous, FAIL
            return UpsertResult(
                name=name,
                action=UpsertAction.FAIL,
                reason=f"Partial overlap: {existing_constraint} and {new_constraint}",
                new_entry=new_entry,
                error=f"Partial overlap between {existing_constraint} and {new_constraint} requires manual resolution",
            )

    # If we get here, either INSERT alongside or REPLACE
    if entries_to_replace:
        return UpsertResult(
            name=name,
            action=UpsertAction.REPLACE,
            reason=f"Replacing {len(entries_to_replace)} entry(ies)",
            new_entry=new_entry,
            replaced_entries=entries_to_replace,
        )
    else:
        return UpsertResult(
            name=name,
            action=UpsertAction.INSERT,
            reason=f"Disjoint kamiwaza_version: {new_constraint}",
            new_entry=new_entry,
        )


def determine_upsert_action_forced(new_entry: dict, existing_entries: list[dict]) -> UpsertResult:
    """Determine upsert action for a forced entry (bypass version checks).

    Force mode: Always INSERT or REPLACE, never FAIL.

    Args:
        new_entry: Entry to upsert
        existing_entries: List of existing entries with same name

    Returns:
        UpsertResult with action and details
    """
    name = new_entry["name"]

    # No existing entry - INSERT
    if not existing_entries:
        return UpsertResult(
            name=name,
            action=UpsertAction.INSERT,
            reason="New extension (forced)",
            new_entry=new_entry,
        )

    # Replace all existing entries with same name
    return UpsertResult(
        name=name,
        action=UpsertAction.REPLACE,
        reason=f"Forced replace of {len(existing_entries)} entry(ies)",
        new_entry=new_entry,
        replaced_entries=existing_entries,
    )


def _determine_upsert_action(
    local_entry: dict,
    existing: list[dict],
    garden_version: str,
    force_entries: set[str],
) -> UpsertResult:
    """Determine the upsert action for a single entry.

    Args:
        local_entry: Entry to upsert
        existing: List of existing entries with same name
        garden_version: Garden version (v1 or v2)
        force_entries: Set of entry names to force (bypass version checks)

    Returns:
        UpsertResult with action and details
    """
    name = local_entry.get("name", "")

    if name in force_entries:
        return determine_upsert_action_forced(local_entry, existing)
    if garden_version in ("1", "default"):
        return determine_upsert_action_v1(local_entry, existing)
    return determine_upsert_action_v2(local_entry, existing)


def merge_entries(
    local_entries: list[dict],
    remote_entries: list[dict],
    garden_version: str,
    force_entries: set[str] | None = None,
) -> MergeResult:
    """Merge local entries with remote entries.

    Args:
        local_entries: Entries from local registry
        remote_entries: Entries from remote registry
        garden_version: Garden version (v1 or v2)
        force_entries: Set of entry names to force (bypass version checks)

    Returns:
        MergeResult with merged entries and action details
    """
    actions = []
    errors = []
    force_entries = force_entries or set()

    # Group remote entries by name
    remote_by_name: dict[str, list[dict]] = {}
    for entry in remote_entries:
        name = entry.get("name", "")
        if name not in remote_by_name:
            remote_by_name[name] = []
        remote_by_name[name].append(entry)

    # Track entries to keep from remote (not replaced)
    entries_to_remove = set()

    # Process each local entry
    for local_entry in local_entries:
        name = local_entry.get("name", "")
        existing = remote_by_name.get(name, [])
        result = _determine_upsert_action(local_entry, existing, garden_version, force_entries)
        actions.append(result)

        if result.action == UpsertAction.FAIL:
            errors.append(result.error or result.reason)
        elif result.action == UpsertAction.REPLACE:
            # Mark replaced entries for removal
            for replaced in result.replaced_entries:
                # Create a hashable key for the entry
                key = (replaced.get("name"), replaced.get("version"), replaced.get("kamiwaza_version"))
                entries_to_remove.add(key)

    # If any errors, return failure
    if errors:
        return MergeResult(
            success=False,
            merged_entries=[],
            actions=actions,
            errors=errors,
        )

    # Build merged entry list
    merged = []

    # Keep remote entries not being replaced
    for entry in remote_entries:
        key = (entry.get("name"), entry.get("version"), entry.get("kamiwaza_version"))
        if key not in entries_to_remove:
            merged.append(entry)

    # Add local entries (INSERT and REPLACE actions)
    for action in actions:
        if action.action in (UpsertAction.INSERT, UpsertAction.REPLACE):
            merged.append(action.new_entry)

    return MergeResult(
        success=True,
        merged_entries=merged,
        actions=actions,
        errors=[],
    )


def merge_registries(
    local_path: Path,
    remote_path: Path,
    output_path: Path,
    garden_version: str,
    force_entries: set[str] | None = None,
) -> tuple[bool, MergeResult, MergeResult]:
    """Merge local and remote registries.

    Args:
        local_path: Path to local registry directory
        remote_path: Path to downloaded remote registry
        output_path: Path to write merged registry
        garden_version: Garden version (v1 or v2)
        force_entries: Set of entry names to force (bypass version checks)

    Returns:
        Tuple of (success, apps_result, tools_result)
    """
    garden_dir = "default" if garden_version == "1" else f"v{garden_version}"

    # Merge apps
    local_apps = load_registry_json(local_path / garden_dir / "apps.json")
    remote_apps = load_registry_json(remote_path / "apps.json")
    apps_result = merge_entries(local_apps, remote_apps, garden_version, force_entries)

    # Merge tools
    local_tools = load_registry_json(local_path / garden_dir / "tools.json")
    remote_tools = load_registry_json(remote_path / "tools.json")
    tools_result = merge_entries(local_tools, remote_tools, garden_version, force_entries)

    # Write output if successful
    if apps_result.success and tools_result.success:
        output_path.mkdir(parents=True, exist_ok=True)
        save_registry_json(output_path / "apps.json", apps_result.merged_entries)
        save_registry_json(output_path / "tools.json", tools_result.merged_entries)

        # Copy images directory if present
        import shutil

        images_dir = "images" if garden_version != "1" else "app-garden-images"

        local_images = local_path / garden_dir / images_dir
        if local_images.exists():
            shutil.copytree(local_images, output_path / images_dir, dirs_exist_ok=True)

        remote_images = remote_path / images_dir
        if remote_images.exists():
            shutil.copytree(remote_images, output_path / images_dir, dirs_exist_ok=True)

    success = apps_result.success and tools_result.success
    return success, apps_result, tools_result


def print_merge_summary(apps_result: MergeResult, tools_result: MergeResult) -> None:
    """Print a summary of merge results."""
    print("\n=== Merge Summary ===\n")

    for name, result in [("Apps", apps_result), ("Tools", tools_result)]:
        if not result or not result.actions:
            print(f"{name}: (none)")
            continue

        print(f"{name}:")
        inserts = [a for a in result.actions if a.action == UpsertAction.INSERT]
        replaces = [a for a in result.actions if a.action == UpsertAction.REPLACE]
        fails = [a for a in result.actions if a.action == UpsertAction.FAIL]

        print(f"  INSERT:  {len(inserts)}")
        print(f"  REPLACE: {len(replaces)}")
        print(f"  FAIL:    {len(fails)}")

        # Show details for each action
        if inserts:
            print("  Inserts:")
            for a in inserts:
                version = a.new_entry.get("version", "?")
                kv = a.new_entry.get("kamiwaza_version", "")
                kv_str = f" (kamiwaza: {kv})" if kv else ""
                print(f"    + {a.name} v{version}{kv_str}")

        if replaces:
            print("  Replaces:")
            for a in replaces:
                new_ver = a.new_entry.get("version", "?")
                old_ver = a.replaced_entries[0].get("version", "?") if a.replaced_entries else "?"
                print(f"    ~ {a.name}: {old_ver} -> {new_ver}")

        if fails:
            print("  Failures:")
            for f in fails:
                print(f"    ✗ {f.name}: {f.error}")

        print()

    # Show overall errors
    all_errors = []
    if apps_result and apps_result.errors:
        all_errors.extend(apps_result.errors)
    if tools_result and tools_result.errors:
        all_errors.extend(tools_result.errors)

    if all_errors:
        print("Errors:")
        for err in all_errors:
            print(f"  - {err}")


if __name__ == "__main__":
    # Test merge logic
    print("Testing merge logic...")

    # Test v1 merge
    local_v1 = [
        {"name": "app1", "version": "1.1.0"},
        {"name": "app2", "version": "1.0.0"},
    ]
    remote_v1 = [
        {"name": "app1", "version": "1.0.0"},
    ]

    result = merge_entries(local_v1, remote_v1, "1")
    print(f"\nv1 merge success: {result.success}")
    for action in result.actions:
        print(f"  {action.name}: {action.action.value} - {action.reason}")

    # Test v2 merge
    local_v2 = [
        {"name": "app1", "version": "1.1.0", "kamiwaza_version": ">=0.8.0"},
        {"name": "app2", "version": "1.0.0", "kamiwaza_version": ">=0.9.0"},
    ]
    remote_v2 = [
        {"name": "app1", "version": "1.0.0", "kamiwaza_version": ">=0.8.0"},
    ]

    result = merge_entries(local_v2, remote_v2, "2")
    print(f"\nv2 merge success: {result.success}")
    for action in result.actions:
        print(f"  {action.name}: {action.action.value} - {action.reason}")
