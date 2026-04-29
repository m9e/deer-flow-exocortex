"""Tests for version comparison utilities."""

import sys
from pathlib import Path

import pytest

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.version_compare import (
    ConstraintRelationship,
    VersionComparison,
    compare_constraints,
    compare_versions,
    constraints_equal,
    constraints_overlap,
    is_subset,
    is_superset,
    validate_constraint,
    validate_version,
)


class TestVersionComparison:
    """Tests for extension version comparison."""

    def test_newer_version(self):
        assert compare_versions("1.1.0", "1.0.0") == VersionComparison.NEWER
        assert compare_versions("2.0.0", "1.9.9") == VersionComparison.NEWER
        assert compare_versions("1.0.1", "1.0.0") == VersionComparison.NEWER

    def test_older_version(self):
        assert compare_versions("1.0.0", "1.1.0") == VersionComparison.OLDER
        assert compare_versions("1.9.9", "2.0.0") == VersionComparison.OLDER
        assert compare_versions("1.0.0", "1.0.1") == VersionComparison.OLDER

    def test_same_version(self):
        assert compare_versions("1.0.0", "1.0.0") == VersionComparison.SAME
        assert compare_versions("2.1.3", "2.1.3") == VersionComparison.SAME

    def test_invalid_version(self):
        with pytest.raises(ValueError):
            compare_versions("not-a-version", "1.0.0")


class TestConstraintValidation:
    """Tests for constraint validation."""

    def test_valid_constraints(self):
        assert validate_constraint(">=0.8.0")[0] is True
        assert validate_constraint(">=0.8.0,<1.0.0")[0] is True
        assert validate_constraint(">=1.0.0")[0] is True
        assert validate_constraint("==1.0.0")[0] is True

    def test_invalid_constraints(self):
        assert validate_constraint("")[0] is False
        assert validate_constraint("not-valid")[0] is False

    def test_valid_versions(self):
        assert validate_version("1.0.0")[0] is True
        assert validate_version("0.8.0")[0] is True
        assert validate_version("2.1.3-dev")[0] is True

    def test_invalid_versions(self):
        assert validate_version("")[0] is False


class TestConstraintComparison:
    """Tests for kamiwaza_version constraint comparison."""

    def test_same_constraints(self):
        assert compare_constraints(">=0.8.0", ">=0.8.0") == ConstraintRelationship.SAME
        assert compare_constraints(">=0.8.0,<1.0.0", ">=0.8.0,<1.0.0") == ConstraintRelationship.SAME

    def test_disjoint_constraints(self):
        # Non-overlapping ranges
        result = compare_constraints(">=0.8.0,<0.9.0", ">=0.9.0,<1.0.0")
        assert result == ConstraintRelationship.DISJOINT

        result = compare_constraints(">=0.5.0,<0.6.0", ">=1.0.0")
        assert result == ConstraintRelationship.DISJOINT

    def test_superset_constraints(self):
        # >=0.8.0 covers more versions than >=0.9.0
        result = compare_constraints(">=0.8.0", ">=0.9.0")
        assert result == ConstraintRelationship.SUPERSET

        # >=0.8.0,<1.0.0 covers more than >=0.9.0,<1.0.0
        result = compare_constraints(">=0.8.0,<1.0.0", ">=0.9.0,<1.0.0")
        assert result == ConstraintRelationship.SUPERSET

    def test_subset_constraints(self):
        # >=0.9.0 is subset of >=0.8.0
        result = compare_constraints(">=0.9.0", ">=0.8.0")
        assert result == ConstraintRelationship.SUBSET

        # >=0.9.0,<1.0.0 is subset of >=0.8.0,<1.0.0
        result = compare_constraints(">=0.9.0,<1.0.0", ">=0.8.0,<1.0.0")
        assert result == ConstraintRelationship.SUBSET

    def test_partial_overlap_constraints(self):
        # Partial overlap: 0.8.0-0.9.5 and 0.9.0-1.0.0
        result = compare_constraints(">=0.8.0,<0.9.5", ">=0.9.0,<1.0.0")
        assert result == ConstraintRelationship.PARTIAL


class TestConstraintOverlap:
    """Tests for constraint overlap detection."""

    def test_overlapping_ranges(self):
        assert constraints_overlap(">=0.8.0", ">=0.9.0") is True
        assert constraints_overlap(">=0.8.0,<1.0.0", ">=0.9.0,<1.1.0") is True

    def test_non_overlapping_ranges(self):
        assert constraints_overlap(">=0.8.0,<0.9.0", ">=0.9.0,<1.0.0") is False
        assert constraints_overlap(">=0.5.0,<0.6.0", ">=1.0.0,<2.0.0") is False


class TestSupersetSubset:
    """Tests for superset/subset detection."""

    def test_is_superset(self):
        # >=0.8.0 covers all versions >=0.9.0 covers
        assert is_superset(">=0.8.0", ">=0.9.0") is True
        # But not the reverse
        assert is_superset(">=0.9.0", ">=0.8.0") is False

    def test_is_subset(self):
        # >=0.9.0 is contained by >=0.8.0
        assert is_subset(">=0.9.0", ">=0.8.0") is True
        # But not the reverse
        assert is_subset(">=0.8.0", ">=0.9.0") is False


class TestConstraintEquality:
    """Tests for constraint equality."""

    def test_equal_constraints(self):
        assert constraints_equal(">=0.8.0", ">=0.8.0") is True
        assert constraints_equal(">=0.8.0,<1.0.0", ">=0.8.0,<1.0.0") is True

    def test_unequal_constraints(self):
        assert constraints_equal(">=0.8.0", ">=0.9.0") is False
        assert constraints_equal(">=0.8.0,<1.0.0", ">=0.8.0,<0.9.0") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
