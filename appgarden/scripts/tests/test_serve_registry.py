"""Tests for serve-registry.py helper behavior."""

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "serve-registry.py"
SPEC = importlib.util.spec_from_file_location("serve_registry", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load module from {MODULE_PATH}")
serve_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(serve_registry)


def test_detect_garden_dir_prefers_repo_version(tmp_path, monkeypatch):
    (tmp_path / ".repo-version").write_text("3\n")
    garden_dir = tmp_path / "garden" / "v3"
    garden_dir.mkdir(parents=True)
    (garden_dir / "apps.json").write_text("[]")

    monkeypatch.delenv("KAMIWAZA_REGISTRY_GARDEN_DIR", raising=False)

    assert serve_registry.detect_garden_dir(tmp_path) == "v3"


def test_detect_garden_dir_can_use_env_override(tmp_path, monkeypatch):
    default_dir = tmp_path / "garden" / "default"
    default_dir.mkdir(parents=True)
    (default_dir / "apps.json").write_text("[]")

    override_dir = tmp_path / "garden" / "v7"
    override_dir.mkdir(parents=True)
    (override_dir / "tools.json").write_text("[]")

    monkeypatch.setenv("KAMIWAZA_REGISTRY_GARDEN_DIR", "v7")

    assert serve_registry.detect_garden_dir(tmp_path) == "v7"
