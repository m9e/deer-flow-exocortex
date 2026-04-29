"""Tests for registry merge logic."""

import sys
from pathlib import Path

import pytest

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.registry_merge import (
    UpsertAction,
    determine_upsert_action_v1,
    determine_upsert_action_v2,
    merge_entries,
    validate_entry,
)


class TestEntryValidation:
    """Tests for registry entry validation."""

    def test_valid_v1_entry(self):
        entry = {"name": "test-app", "version": "1.0.0"}
        errors = validate_entry(entry, "1")
        assert len(errors) == 0

    def test_valid_v2_entry(self):
        entry = {"name": "test-app", "version": "1.0.0", "kamiwaza_version": ">=0.8.0"}
        errors = validate_entry(entry, "2")
        assert len(errors) == 0

    def test_missing_name(self):
        entry = {"version": "1.0.0"}
        errors = validate_entry(entry, "1")
        assert any("name" in e for e in errors)

    def test_missing_version(self):
        entry = {"name": "test-app"}
        errors = validate_entry(entry, "1")
        assert any("version" in e for e in errors)

    def test_v2_requires_kamiwaza_version(self):
        entry = {"name": "test-app", "version": "1.0.0"}
        errors = validate_entry(entry, "2")
        assert any("kamiwaza_version" in e for e in errors)

    def test_invalid_version_format(self):
        entry = {"name": "test-app", "version": "not-valid"}
        errors = validate_entry(entry, "1")
        assert any("Invalid version" in e for e in errors)

    def test_invalid_kamiwaza_version_format(self):
        entry = {"name": "test-app", "version": "1.0.0", "kamiwaza_version": "not-valid"}
        errors = validate_entry(entry, "2")
        assert any("Invalid kamiwaza_version" in e for e in errors)


class TestV1UpsertLogic:
    """Tests for v1 (garden/default) upsert logic."""

    def test_insert_new_extension(self):
        """New extension should INSERT."""
        new_entry = {"name": "new-app", "version": "1.0.0"}
        result = determine_upsert_action_v1(new_entry, [])
        assert result.action == UpsertAction.INSERT

    def test_replace_with_newer_version(self):
        """Newer version should REPLACE."""
        new_entry = {"name": "app", "version": "1.1.0"}
        existing = [{"name": "app", "version": "1.0.0"}]
        result = determine_upsert_action_v1(new_entry, existing)
        assert result.action == UpsertAction.REPLACE
        assert len(result.replaced_entries) == 1

    def test_fail_same_version(self):
        """Same version should FAIL (immutable)."""
        new_entry = {"name": "app", "version": "1.0.0"}
        existing = [{"name": "app", "version": "1.0.0"}]
        result = determine_upsert_action_v1(new_entry, existing)
        assert result.action == UpsertAction.FAIL
        assert "immutable" in result.reason.lower() or "already exists" in result.reason.lower()

    def test_fail_downgrade(self):
        """Downgrade should FAIL."""
        new_entry = {"name": "app", "version": "0.9.0"}
        existing = [{"name": "app", "version": "1.0.0"}]
        result = determine_upsert_action_v1(new_entry, existing)
        assert result.action == UpsertAction.FAIL
        assert "downgrade" in result.reason.lower()


class TestV2UpsertLogic:
    """Tests for v2 upsert logic with kamiwaza_version constraints."""

    def test_insert_new_extension(self):
        """New extension should INSERT."""
        new_entry = {"name": "new-app", "version": "1.0.0", "kamiwaza_version": ">=0.8.0"}
        result = determine_upsert_action_v2(new_entry, [])
        assert result.action == UpsertAction.INSERT

    def test_fail_missing_kamiwaza_version(self):
        """Missing kamiwaza_version should FAIL."""
        new_entry = {"name": "app", "version": "1.0.0"}
        result = determine_upsert_action_v2(new_entry, [])
        assert result.action == UpsertAction.FAIL
        assert "kamiwaza_version" in result.reason.lower()

    def test_replace_same_constraint_newer_version(self):
        """Same constraint with newer version should REPLACE."""
        new_entry = {"name": "app", "version": "1.1.0", "kamiwaza_version": ">=0.8.0"}
        existing = [{"name": "app", "version": "1.0.0", "kamiwaza_version": ">=0.8.0"}]
        result = determine_upsert_action_v2(new_entry, existing)
        assert result.action == UpsertAction.REPLACE

    def test_fail_same_constraint_same_version(self):
        """Same constraint with same version should FAIL (immutable)."""
        new_entry = {"name": "app", "version": "1.0.0", "kamiwaza_version": ">=0.8.0"}
        existing = [{"name": "app", "version": "1.0.0", "kamiwaza_version": ">=0.8.0"}]
        result = determine_upsert_action_v2(new_entry, existing)
        assert result.action == UpsertAction.FAIL

    def test_fail_same_constraint_older_version(self):
        """Same constraint with older version should FAIL (no downgrade)."""
        new_entry = {"name": "app", "version": "0.9.0", "kamiwaza_version": ">=0.8.0"}
        existing = [{"name": "app", "version": "1.0.0", "kamiwaza_version": ">=0.8.0"}]
        result = determine_upsert_action_v2(new_entry, existing)
        assert result.action == UpsertAction.FAIL
        assert "downgrade" in result.reason.lower()

    def test_insert_disjoint_constraints(self):
        """Disjoint constraints should INSERT alongside."""
        new_entry = {"name": "app", "version": "1.1.0", "kamiwaza_version": ">=0.9.0,<1.0.0"}
        existing = [{"name": "app", "version": "1.0.0", "kamiwaza_version": ">=0.8.0,<0.9.0"}]
        result = determine_upsert_action_v2(new_entry, existing)
        assert result.action == UpsertAction.INSERT

    def test_replace_superset_constraint(self):
        """New superset constraint should REPLACE."""
        new_entry = {"name": "app", "version": "1.1.0", "kamiwaza_version": ">=0.8.0"}
        existing = [{"name": "app", "version": "1.0.0", "kamiwaza_version": ">=0.9.0"}]
        result = determine_upsert_action_v2(new_entry, existing)
        assert result.action == UpsertAction.REPLACE

    def test_fail_subset_constraint(self):
        """New subset constraint should FAIL (would narrow support)."""
        new_entry = {"name": "app", "version": "1.1.0", "kamiwaza_version": ">=0.9.0"}
        existing = [{"name": "app", "version": "1.0.0", "kamiwaza_version": ">=0.8.0"}]
        result = determine_upsert_action_v2(new_entry, existing)
        assert result.action == UpsertAction.FAIL
        assert "narrow" in result.reason.lower()

    def test_fail_partial_overlap(self):
        """Partial overlap should FAIL (ambiguous)."""
        new_entry = {"name": "app", "version": "1.1.0", "kamiwaza_version": ">=0.9.0,<1.0.0"}
        existing = [{"name": "app", "version": "1.0.0", "kamiwaza_version": ">=0.8.0,<0.9.5"}]
        result = determine_upsert_action_v2(new_entry, existing)
        assert result.action == UpsertAction.FAIL
        assert "partial" in result.reason.lower() or "overlap" in result.reason.lower()


class TestMergeEntries:
    """Tests for merging local and remote entries."""

    def test_merge_v1_insert_and_keep(self):
        """Merge should INSERT new and keep unrelated."""
        local = [{"name": "new-app", "version": "1.0.0"}]
        remote = [{"name": "old-app", "version": "2.0.0"}]
        result = merge_entries(local, remote, "1")
        assert result.success is True
        assert len(result.merged_entries) == 2

    def test_merge_v1_replace(self):
        """Merge should REPLACE with newer version."""
        local = [{"name": "app", "version": "1.1.0"}]
        remote = [{"name": "app", "version": "1.0.0"}]
        result = merge_entries(local, remote, "1")
        assert result.success is True
        assert len(result.merged_entries) == 1
        assert result.merged_entries[0]["version"] == "1.1.0"

    def test_merge_v1_fail_blocks_all(self):
        """FAIL on any entry should block entire merge."""
        local = [
            {"name": "app1", "version": "1.1.0"},  # Would succeed
            {"name": "app2", "version": "1.0.0"},  # Would fail - same version
        ]
        remote = [
            {"name": "app1", "version": "1.0.0"},
            {"name": "app2", "version": "1.0.0"},
        ]
        result = merge_entries(local, remote, "1")
        assert result.success is False
        assert len(result.errors) > 0

    def test_merge_v2_insert_disjoint(self):
        """Merge v2 should INSERT with disjoint constraints."""
        local = [{"name": "app", "version": "1.0.0", "kamiwaza_version": ">=0.9.0,<1.0.0"}]
        remote = [{"name": "app", "version": "1.0.0", "kamiwaza_version": ">=0.8.0,<0.9.0"}]
        result = merge_entries(local, remote, "2")
        assert result.success is True
        # Both entries should coexist
        assert len(result.merged_entries) == 2

    def test_merge_v2_replace_superset(self):
        """Merge v2 should REPLACE when new is superset."""
        local = [{"name": "app", "version": "1.1.0", "kamiwaza_version": ">=0.8.0,<1.0.0"}]
        remote = [{"name": "app", "version": "1.0.0", "kamiwaza_version": ">=0.9.0,<1.0.0"}]
        result = merge_entries(local, remote, "2")
        assert result.success is True
        assert len(result.merged_entries) == 1
        assert result.merged_entries[0]["version"] == "1.1.0"


class TestMergeResultActions:
    """Tests for tracking merge actions."""

    def test_tracks_insert_actions(self):
        local = [{"name": "new-app", "version": "1.0.0"}]
        remote: list[dict[str, str]] = []
        result = merge_entries(local, remote, "1")
        inserts = [a for a in result.actions if a.action == UpsertAction.INSERT]
        assert len(inserts) == 1

    def test_tracks_replace_actions(self):
        local = [{"name": "app", "version": "1.1.0"}]
        remote = [{"name": "app", "version": "1.0.0"}]
        result = merge_entries(local, remote, "1")
        replaces = [a for a in result.actions if a.action == UpsertAction.REPLACE]
        assert len(replaces) == 1

    def test_tracks_fail_actions(self):
        local = [{"name": "app", "version": "1.0.0"}]
        remote = [{"name": "app", "version": "1.0.0"}]
        result = merge_entries(local, remote, "1")
        fails = [a for a in result.actions if a.action == UpsertAction.FAIL]
        assert len(fails) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
