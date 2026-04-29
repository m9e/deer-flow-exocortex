"""Tests for sync-compose image handling."""

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "sync-compose.py"
SPEC = importlib.util.spec_from_file_location("sync_compose", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load module from {MODULE_PATH}")
sync_compose = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_compose)


@pytest.fixture(autouse=True)
def reset_image_prefix():
    """Reset IMAGE_PREFIX after each test."""
    original = sync_compose.IMAGE_PREFIX
    try:
        yield
    finally:
        sync_compose.IMAGE_PREFIX = original


def test_is_extension_image_matches_literal_prefix():
    sync_compose.IMAGE_PREFIX = "ghcr.io/acme/my-repo/images"

    assert sync_compose.is_extension_image("ghcr.io/acme/my-repo/images/my-app-backend:latest")
    assert not sync_compose.is_extension_image("postgres:15-alpine")


def test_is_extension_image_matches_image_prefix_placeholder():
    sync_compose.IMAGE_PREFIX = "ghcr.io/acme/my-repo/images"

    assert sync_compose.is_extension_image("${IMAGE_PREFIX}/my-app-backend:latest")
    assert sync_compose.is_extension_image("${IMAGE_PREFIX:-ghcr.io/acme/my-repo/images}/my-app-backend:latest")


def test_update_image_tag_preserves_placeholder_prefix():
    image = "${IMAGE_PREFIX:-ghcr.io/acme/my-repo/images}/my-app-backend:latest"

    assert (
        sync_compose.update_image_tag(image, "1.2.3")
        == "${IMAGE_PREFIX:-ghcr.io/acme/my-repo/images}/my-app-backend:1.2.3"
    )


def test_update_image_tag_handles_registry_ports():
    image = "registry.internal:5000/my-app-backend:latest"

    assert sync_compose.update_image_tag(image, "1.2.3") == "registry.internal:5000/my-app-backend:1.2.3"


def test_transform_service_updates_placeholder_image_tag():
    sync_compose.IMAGE_PREFIX = "ghcr.io/acme/my-repo/images"
    service = {"image": "${IMAGE_PREFIX}/my-app-backend:latest", "ports": ["8000:8000"]}

    transformed = sync_compose.transform_service(service, "backend", version="1.2.3", extension_name="my-app")

    assert transformed["image"] == "${IMAGE_PREFIX}/my-app-backend:1.2.3"
