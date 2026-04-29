"""Tests for build-registry stage-aware image transforms."""

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "build-registry.py"
SPEC = importlib.util.spec_from_file_location("build_registry", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load module from {MODULE_PATH}")
build_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_registry)


@pytest.fixture(autouse=True)
def reset_image_prefix():
    """Reset IMAGE_PREFIX after each test."""
    original = build_registry.IMAGE_PREFIX
    try:
        yield
    finally:
        build_registry.IMAGE_PREFIX = original


def test_transform_image_tag_for_stage_with_custom_prefix():
    build_registry.IMAGE_PREFIX = "ghcr.io/org-name"

    assert (
        build_registry.transform_image_tag_for_stage("ghcr.io/org-name/my-app-backend:v1.2.3", "dev")
        == "ghcr.io/org-name/my-app-backend:1.2.3-dev"
    )


def test_transform_image_tag_for_stage_keeps_external_images():
    build_registry.IMAGE_PREFIX = "ghcr.io/org-name"

    assert build_registry.transform_image_tag_for_stage("postgres:15-alpine", "stage") == "postgres:15-alpine"


def test_transform_image_tag_for_stage_keeps_digest_pinned_images():
    build_registry.IMAGE_PREFIX = "ghcr.io/org-name"
    image = "ghcr.io/org-name/my-app-backend@sha256:" + ("a" * 64)

    assert build_registry.transform_image_tag_for_stage(image, "stage") == image


def test_transform_env_value_for_stage_escapes_image_prefix_regex_chars():
    build_registry.IMAGE_PREFIX = "ghcr.io/org.name"
    value = "${SANDBOX_IMAGE:-ghcr.io/org.name/sandbox:v1.2.3}"

    transformed = build_registry.transform_env_value_for_stage(value, "stage")

    assert transformed == "${SANDBOX_IMAGE:-ghcr.io/org.name/sandbox:1.2.3-stage}"


def test_transform_env_value_for_stage_handles_bare_image_values():
    build_registry.IMAGE_PREFIX = "ghcr.io/org-name"
    value = "ghcr.io/org-name/agent:v1.2.3"

    transformed = build_registry.transform_env_value_for_stage(value, "dev")

    assert transformed == "ghcr.io/org-name/agent:1.2.3-dev"
