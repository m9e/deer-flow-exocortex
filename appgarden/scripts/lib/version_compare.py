"""Version comparison utilities for registry upsert.

Provides functions to compare semver constraints (kamiwaza_version) and
extension versions to determine upsert actions.
"""

from enum import Enum

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


class ConstraintRelationship(Enum):
    """Relationship between two version constraints."""

    DISJOINT = "disjoint"  # No overlap
    SAME = "same"  # Exactly the same
    SUPERSET = "superset"  # First contains second
    SUBSET = "subset"  # Second contains first
    PARTIAL = "partial"  # Overlapping but neither contains the other


class VersionComparison(Enum):
    """Result of comparing two extension versions."""

    NEWER = "newer"  # First is newer than second
    SAME = "same"  # Same version
    OLDER = "older"  # First is older than second


def parse_version(version_str: str) -> Version:
    """Parse a version string into a Version object.

    Args:
        version_str: Version string (e.g., "1.0.0", "1.2.3-dev")

    Returns:
        Parsed Version object

    Raises:
        ValueError if version string is invalid
    """
    try:
        return Version(version_str)
    except InvalidVersion as e:
        raise ValueError(f"Invalid version string '{version_str}': {e}")


def parse_constraint(constraint_str: str) -> SpecifierSet:
    """Parse a version constraint string into a SpecifierSet.

    Args:
        constraint_str: Constraint string (e.g., ">=0.8.0", ">=0.8.0,<1.0.0")

    Returns:
        Parsed SpecifierSet object

    Raises:
        ValueError if constraint string is invalid
    """
    try:
        return SpecifierSet(constraint_str)
    except InvalidSpecifier as e:
        raise ValueError(f"Invalid constraint string '{constraint_str}': {e}")


def compare_versions(v1: str, v2: str) -> VersionComparison:
    """Compare two extension version strings.

    Args:
        v1: First version string
        v2: Second version string

    Returns:
        VersionComparison indicating relationship
    """
    ver1 = parse_version(v1)
    ver2 = parse_version(v2)

    if ver1 > ver2:
        return VersionComparison.NEWER
    elif ver1 < ver2:
        return VersionComparison.OLDER
    else:
        return VersionComparison.SAME


def generate_test_versions() -> list[Version]:
    """Generate a comprehensive list of test versions for constraint comparison.

    Returns a list of versions that covers common semver patterns to test
    constraint overlap and containment.
    """
    versions = []

    # Generate versions from 0.1.0 to 2.0.0
    for major in range(3):
        for minor in range(20):
            for patch in range(5):
                versions.append(Version(f"{major}.{minor}.{patch}"))

    # Add some specific versions that are commonly used
    specific = [
        "0.8.0",
        "0.8.1",
        "0.9.0",
        "0.9.5",
        "0.10.0",
        "1.0.0",
        "1.0.1",
        "1.1.0",
        "1.2.0",
    ]
    for v in specific:
        ver = Version(v)
        if ver not in versions:
            versions.append(ver)

    return sorted(versions)


# Cache test versions for performance
_TEST_VERSIONS: list[Version] | None = None


def get_test_versions() -> list[Version]:
    """Get cached test versions."""
    global _TEST_VERSIONS
    if _TEST_VERSIONS is None:
        _TEST_VERSIONS = generate_test_versions()
    return _TEST_VERSIONS


def constraints_overlap(c1: str, c2: str) -> bool:
    """Check if two version constraints have any overlap.

    Args:
        c1: First constraint string
        c2: Second constraint string

    Returns:
        True if there exists at least one version that satisfies both constraints
    """
    spec1 = parse_constraint(c1)
    spec2 = parse_constraint(c2)

    # Check if any test version satisfies both constraints
    for version in get_test_versions():
        if version in spec1 and version in spec2:
            return True

    return False


def is_superset(c1: str, c2: str) -> bool:
    """Check if c1 is a superset of c2.

    c1 is a superset of c2 if every version that satisfies c2 also satisfies c1.

    Args:
        c1: First constraint string (potential superset)
        c2: Second constraint string (potential subset)

    Returns:
        True if c1 covers all versions that c2 covers
    """
    spec1 = parse_constraint(c1)
    spec2 = parse_constraint(c2)

    # Check if every version that satisfies c2 also satisfies c1
    for version in get_test_versions():
        if version in spec2 and version not in spec1:
            return False

    return True


def is_subset(c1: str, c2: str) -> bool:
    """Check if c1 is a subset of c2.

    c1 is a subset of c2 if every version that satisfies c1 also satisfies c2.

    Args:
        c1: First constraint string (potential subset)
        c2: Second constraint string (potential superset)

    Returns:
        True if c2 covers all versions that c1 covers
    """
    return is_superset(c2, c1)


def constraints_equal(c1: str, c2: str) -> bool:
    """Check if two constraints are equivalent (same set of versions).

    Args:
        c1: First constraint string
        c2: Second constraint string

    Returns:
        True if both constraints match exactly the same versions
    """
    spec1 = parse_constraint(c1)
    spec2 = parse_constraint(c2)

    # Check if constraints match the same versions
    for version in get_test_versions():
        if (version in spec1) != (version in spec2):
            return False

    return True


def compare_constraints(c1: str, c2: str) -> ConstraintRelationship:
    """Compare two version constraints and determine their relationship.

    Args:
        c1: First constraint string
        c2: Second constraint string

    Returns:
        ConstraintRelationship indicating how c1 relates to c2
    """
    # First check for equality
    if constraints_equal(c1, c2):
        return ConstraintRelationship.SAME

    # Check for overlap
    if not constraints_overlap(c1, c2):
        return ConstraintRelationship.DISJOINT

    # Check for superset/subset
    c1_superset = is_superset(c1, c2)
    c2_superset = is_superset(c2, c1)

    if c1_superset and not c2_superset:
        return ConstraintRelationship.SUPERSET
    elif c2_superset and not c1_superset:
        return ConstraintRelationship.SUBSET
    else:
        # Overlapping but neither is a superset
        return ConstraintRelationship.PARTIAL


def validate_constraint(constraint_str: str) -> tuple[bool, str | None]:
    """Validate a version constraint string.

    Args:
        constraint_str: Constraint string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not constraint_str:
        return False, "Constraint string is empty"

    try:
        parse_constraint(constraint_str)
        return True, None
    except ValueError as e:
        return False, str(e)


def validate_version(version_str: str) -> tuple[bool, str | None]:
    """Validate a version string.

    Args:
        version_str: Version string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not version_str:
        return False, "Version string is empty"

    try:
        parse_version(version_str)
        return True, None
    except ValueError as e:
        return False, str(e)


if __name__ == "__main__":
    # Simple test cases
    print("Testing version comparison:")
    print(f"  1.0.0 vs 1.0.1: {compare_versions('1.0.0', '1.0.1')}")
    print(f"  1.1.0 vs 1.0.1: {compare_versions('1.1.0', '1.0.1')}")
    print(f"  1.0.0 vs 1.0.0: {compare_versions('1.0.0', '1.0.0')}")

    print("\nTesting constraint comparison:")
    test_cases = [
        (">=0.8.0", ">=0.8.0"),  # SAME
        (">=0.8.0", ">=0.9.0"),  # SUPERSET (0.8 covers more)
        (">=0.9.0", ">=0.8.0"),  # SUBSET
        (">=0.8.0,<0.9.0", ">=0.9.0,<1.0.0"),  # DISJOINT
        (">=0.8.0,<1.0.0", ">=0.9.0,<1.0.0"),  # SUPERSET
        (">=0.8.0,<0.9.5", ">=0.9.0,<1.0.0"),  # PARTIAL
    ]

    for c1, c2 in test_cases:
        result = compare_constraints(c1, c2)
        print(f"  '{c1}' vs '{c2}': {result.value}")
