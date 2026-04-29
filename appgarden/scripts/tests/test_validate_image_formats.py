"""Regression tests for image format validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

VALIDATE_COMPOSE_PATH = Path(__file__).resolve().parents[1] / "validate-compose.py"
VALIDATE_COMPOSE_SPEC = importlib.util.spec_from_file_location("validate_compose", VALIDATE_COMPOSE_PATH)
if VALIDATE_COMPOSE_SPEC is None or VALIDATE_COMPOSE_SPEC.loader is None:
    raise RuntimeError(f"Could not load module from {VALIDATE_COMPOSE_PATH}")
validate_compose = importlib.util.module_from_spec(VALIDATE_COMPOSE_SPEC)
VALIDATE_COMPOSE_SPEC.loader.exec_module(validate_compose)

VALIDATE_METADATA_PATH = Path(__file__).resolve().parents[1] / "validate-metadata.py"
VALIDATE_METADATA_SPEC = importlib.util.spec_from_file_location("validate_metadata", VALIDATE_METADATA_PATH)
if VALIDATE_METADATA_SPEC is None or VALIDATE_METADATA_SPEC.loader is None:
    raise RuntimeError(f"Could not load module from {VALIDATE_METADATA_PATH}")
validate_metadata = importlib.util.module_from_spec(VALIDATE_METADATA_SPEC)
VALIDATE_METADATA_SPEC.loader.exec_module(validate_metadata)


def test_validate_compose_accepts_port_bearing_registry_image() -> None:
    service = {"image": "registry.internal:5000/acme/repo/images/demo:1.0.0"}

    assert validate_compose._check_image_format(service, "demo") == []


def test_validate_compose_accepts_image_prefix_placeholder() -> None:
    service = {"image": "${IMAGE_PREFIX:-ghcr.io/acme/repo/images}/demo-app-backend:1.0.0"}

    assert validate_compose._check_image_format(service, "demo") == []


def test_validate_compose_accepts_image_prefix_variable() -> None:
    service = {"image": "${IMAGE_PREFIX}/demo-app-backend:1.0.0"}

    assert validate_compose._check_image_format(service, "demo") == []


def test_validate_metadata_accepts_port_bearing_registry_image() -> None:
    assert validate_metadata.IMAGE_REFERENCE_PATTERN.match(
        "registry.internal:5000/acme/repo/images/demo:1.0.0"
    )
