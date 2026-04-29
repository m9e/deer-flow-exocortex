"""Regression tests for converter/deployer image prefix resolution."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONVERT_PATH = REPO_ROOT / ".claude" / "skills" / "kz-appgarden-converter" / "convert.py"
DEPLOY_PATH = REPO_ROOT / ".claude" / "skills" / "kz-appgarden-converter" / "deploy.py"
CHECK_LOCAL_PATH = REPO_ROOT / "scripts" / "check-local-extension-images.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_convert_resolve_image_prefix_uses_target_repo_helper(tmp_path: Path, monkeypatch) -> None:
    convert = load_module("converter_module", CONVERT_PATH)
    monkeypatch.delenv("IMAGE_PREFIX", raising=False)

    output_repo = tmp_path / "kamiwaza-appgarden-demo"
    scripts_dir = output_repo / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "image_prefix.py").write_text(
        "def get_image_prefix(script_path=None):\n"
        "    return 'ghcr.io/test-org/generated-output/images'\n",
        encoding="utf-8",
    )

    assert convert.resolve_image_prefix(output_repo) == "ghcr.io/test-org/generated-output/images"


def test_convert_resolve_image_prefix_falls_back_when_helper_is_invalid(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    convert = load_module("converter_invalid_helper_module", CONVERT_PATH)
    monkeypatch.delenv("IMAGE_PREFIX", raising=False)

    output_repo = tmp_path / "kamiwaza-appgarden-demo"
    scripts_dir = output_repo / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "image_prefix.py").write_text("def broken(:\n", encoding="utf-8")

    assert convert.resolve_image_prefix(output_repo) == "ghcr.io/kamiwaza-internal/kamiwaza-appgarden-demo/images"
    assert "warning: failed to load" in capsys.readouterr().err


def test_convert_resolve_image_prefix_falls_back_to_output_repo_name(tmp_path: Path, monkeypatch) -> None:
    convert = load_module("converter_fallback_module", CONVERT_PATH)
    monkeypatch.delenv("IMAGE_PREFIX", raising=False)

    output_repo = tmp_path / "Kamiwaza_AppGarden_Demo"
    output_repo.mkdir()

    assert convert.resolve_image_prefix(output_repo) == "ghcr.io/kamiwaza-internal/kamiwaza-appgarden-demo/images"


def test_deploy_resolve_image_prefix_uses_target_repo_helper(tmp_path: Path, monkeypatch) -> None:
    deploy = load_module("deploy_module", DEPLOY_PATH)
    monkeypatch.delenv("IMAGE_PREFIX", raising=False)

    repo_root = tmp_path / "kamiwaza-appgarden-demo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "image_prefix.py").write_text(
        "def get_image_prefix(script_path=None):\n"
        "    return 'ghcr.io/test-org/deploy-target/images'\n",
        encoding="utf-8",
    )

    assert deploy.resolve_image_prefix(repo_root) == "ghcr.io/test-org/deploy-target/images"


def test_deploy_resolve_image_prefix_falls_back_when_helper_signature_is_wrong(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    deploy = load_module("deploy_invalid_helper_module", DEPLOY_PATH)
    monkeypatch.delenv("IMAGE_PREFIX", raising=False)

    repo_root = tmp_path / "kamiwaza-appgarden-demo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "image_prefix.py").write_text(
        "def get_image_prefix():\n"
        "    return 'ghcr.io/test-org/ignored/images'\n",
        encoding="utf-8",
    )

    assert deploy.resolve_image_prefix(repo_root) == "ghcr.io/kamiwaza-internal/kamiwaza-appgarden-demo/images"
    assert "warning: failed to resolve IMAGE_PREFIX via" in capsys.readouterr().err


def test_check_local_help_does_not_resolve_image_prefix(monkeypatch) -> None:
    check_local = load_module("check_local_module", CHECK_LOCAL_PATH)

    def fail(*args, **kwargs):
        raise AssertionError("get_image_prefix should not be called for --help")

    monkeypatch.setattr(check_local, "get_image_prefix", fail)
    monkeypatch.setattr(sys, "argv", ["check-local-extension-images.py", "--help"])

    with pytest.raises(SystemExit) as excinfo:
        check_local.main()

    assert excinfo.value.code == 0


def test_check_local_explicit_image_prefix_skips_default_resolution(monkeypatch, capsys) -> None:
    check_local = load_module("check_local_explicit_module", CHECK_LOCAL_PATH)

    def fail(*args, **kwargs):
        raise AssertionError("get_image_prefix should not be called when --image-prefix is provided")

    monkeypatch.setattr(check_local, "get_image_prefix", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check-local-extension-images.py",
            "--type",
            "app",
            "--name",
            "missing-app",
            "--image-prefix",
            "ghcr.io/test-org/demo/images",
        ],
    )

    check_local.main()

    output = capsys.readouterr().out
    assert "Warning:" in output
    assert (
        "Registry file not found for local image check:" in output
        or "Could not find registry entry for app/missing-app" in output
    )


def test_convert_resolve_image_prefix_lowercases_env_override(tmp_path: Path, monkeypatch) -> None:
    convert = load_module("converter_env_lowercase_module", CONVERT_PATH)
    monkeypatch.setenv("IMAGE_PREFIX", "ghcr.io/MyOrg/MyRepo/Images/")

    output_repo = tmp_path / "kamiwaza-appgarden-demo"
    output_repo.mkdir()

    assert convert.resolve_image_prefix(output_repo) == "ghcr.io/myorg/myrepo/images"


def test_deploy_resolve_image_prefix_lowercases_env_override(tmp_path: Path, monkeypatch) -> None:
    deploy = load_module("deploy_env_lowercase_module", DEPLOY_PATH)
    monkeypatch.setenv("IMAGE_PREFIX", "ghcr.io/MyOrg/MyRepo/Images/")

    repo_root = tmp_path / "kamiwaza-appgarden-demo"
    repo_root.mkdir()

    assert deploy.resolve_image_prefix(repo_root) == "ghcr.io/myorg/myrepo/images"
