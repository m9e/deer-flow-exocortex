#!/usr/bin/env python3
"""
Tests for build-registry.py
"""

import sys
from pathlib import Path

# Add scripts directory to path to import build-registry functions
sys.path.insert(0, str(Path(__file__).parent))

# Import the function we're testing
# Note: This requires Python 3.9+ for direct import of module with hyphen
import importlib.util

spec = importlib.util.spec_from_file_location("build_registry", Path(__file__).parent / "build-registry.py")
build_registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_registry)

validate_duplicate_preview_images = build_registry.validate_duplicate_preview_images


def test_no_duplicates():
    """Test that no duplicates returns empty error list."""
    apps = [
        {"name": "App1", "preview_image": "/app-garden-images/app1.png"},
        {"name": "App2", "preview_image": "/app-garden-images/app2.png"},
        {"name": "App3", "preview_image": None},
    ]
    tools = [
        {"name": "Tool1", "preview_image": "/app-garden-images/tool1.png"},
        {"name": "Tool2", "preview_image": None},
    ]

    errors = validate_duplicate_preview_images(apps, tools)
    assert errors == [], f"Expected no errors, got: {errors}"
    print("✓ test_no_duplicates passed")


def test_duplicate_preview_images():
    """Test that duplicate preview_images are detected."""
    apps = [
        {"name": "App1", "preview_image": "/app-garden-images/shared.png"},
        {"name": "App2", "preview_image": "/app-garden-images/app2.png"},
    ]
    tools = [
        {"name": "Tool1", "preview_image": "/app-garden-images/shared.png"},
    ]

    errors = validate_duplicate_preview_images(apps, tools)
    assert len(errors) == 1, f"Expected 1 error, got {len(errors)}: {errors}"
    assert "shared.png" in errors[0], f"Expected 'shared.png' in error: {errors[0]}"
    assert "App1" in errors[0], f"Expected 'App1' in error: {errors[0]}"
    assert "Tool1" in errors[0], f"Expected 'Tool1' in error: {errors[0]}"
    print("✓ test_duplicate_preview_images passed")


def test_null_values_not_duplicates():
    """Test that null values are not treated as duplicates."""
    apps = [
        {"name": "App1", "preview_image": None},
        {"name": "App2", "preview_image": None},
        {"name": "App3"},  # Missing preview_image key
    ]
    tools = [
        {"name": "Tool1", "preview_image": None},
    ]

    errors = validate_duplicate_preview_images(apps, tools)
    assert errors == [], f"Expected no errors for null values, got: {errors}"
    print("✓ test_null_values_not_duplicates passed")


def test_multiple_duplicates():
    """Test detection of multiple different duplicate groups."""
    apps = [
        {"name": "App1", "preview_image": "/app-garden-images/dup1.png"},
        {"name": "App2", "preview_image": "/app-garden-images/dup1.png"},
        {"name": "App3", "preview_image": "/app-garden-images/dup2.png"},
    ]
    tools = [
        {"name": "Tool1", "preview_image": "/app-garden-images/dup2.png"},
    ]

    errors = validate_duplicate_preview_images(apps, tools)
    assert len(errors) == 2, f"Expected 2 errors, got {len(errors)}: {errors}"
    print("✓ test_multiple_duplicates passed")


def run_all_tests():
    """Run all tests."""
    print("Running build-registry.py tests...\n")

    try:
        test_no_duplicates()
        test_duplicate_preview_images()
        test_null_values_not_duplicates()
        test_multiple_duplicates()

        print("\n✅ All tests passed!")
        return 0

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
