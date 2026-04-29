"""Tests for IMAGE_PREFIX helper resolution."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "image_prefix.py"
SPEC = importlib.util.spec_from_file_location("image_prefix", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load module from {MODULE_PATH}")
image_prefix = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(image_prefix)

DEFAULT_IMAGE_PREFIX_SCRIPT = Path(__file__).resolve().parents[1] / "default-image-prefix.sh"


def test_get_default_image_prefix_falls_back_on_os_error(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)
    caller = scripts_dir / "caller.py"
    caller.write_text("", encoding="utf-8")

    original_run = image_prefix.subprocess.run

    def raise_permission_error(args, **kwargs):
        if args == [str(repo_root / "scripts" / "default-image-prefix.sh")]:
            raise PermissionError("helper is not executable")
        return original_run(args, **kwargs)

    monkeypatch.setattr(image_prefix.subprocess, "run", raise_permission_error)

    assert image_prefix.get_default_image_prefix(caller) == "ghcr.io/kamiwaza-internal/demo-repo/images"


def test_get_default_image_prefix_warns_when_helper_fails(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)
    caller = scripts_dir / "caller.py"
    caller.write_text("", encoding="utf-8")

    original_run = image_prefix.subprocess.run

    def raise_permission_error(args, **kwargs):
        if args == [str(repo_root / "scripts" / "default-image-prefix.sh")]:
            raise PermissionError("helper is not executable")
        return original_run(args, **kwargs)

    monkeypatch.setattr(image_prefix.subprocess, "run", raise_permission_error)

    assert image_prefix.get_default_image_prefix(caller) == "ghcr.io/kamiwaza-internal/demo-repo/images"
    assert "warning: failed to resolve IMAGE_PREFIX via default-image-prefix.sh" in capsys.readouterr().err


def test_get_default_image_prefix_normalizes_fallback_repo_name(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "Demo_Repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)
    caller = scripts_dir / "caller.py"
    caller.write_text("", encoding="utf-8")

    original_run = image_prefix.subprocess.run

    def raise_permission_error(args, **kwargs):
        if args == [str(repo_root / "scripts" / "default-image-prefix.sh")]:
            raise PermissionError("helper is not executable")
        return original_run(args, **kwargs)

    monkeypatch.setattr(image_prefix.subprocess, "run", raise_permission_error)

    assert image_prefix.get_default_image_prefix(caller) == "ghcr.io/kamiwaza-internal/demo-repo/images"


def test_get_default_image_prefix_uses_answers_when_helper_fails(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)
    caller = scripts_dir / "caller.py"
    caller.write_text("", encoding="utf-8")
    (repo_root / ".copier-answers.yml").write_text(
        'image_prefix: "registry.internal:5000/Acme/Repo_Images"\n',
        encoding="utf-8",
    )

    original_run = image_prefix.subprocess.run

    def raise_permission_error(args, **kwargs):
        if args == [str(repo_root / "scripts" / "default-image-prefix.sh")]:
            raise PermissionError("helper is not executable")
        return original_run(args, **kwargs)

    monkeypatch.setattr(image_prefix.subprocess, "run", raise_permission_error)

    assert image_prefix.get_default_image_prefix(caller) == "registry.internal:5000/acme/repo-images"


def test_get_default_image_prefix_uses_git_remote_when_helper_fails(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)
    caller = scripts_dir / "caller.py"
    caller.write_text("", encoding="utf-8")

    subprocess.run(["git", "init"], check=True, cwd=repo_root, capture_output=True, text=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/MyOrg/My_Repo.git/"],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    original_run = image_prefix.subprocess.run

    def flaky_run(args, **kwargs):
        if args == [str(repo_root / "scripts" / "default-image-prefix.sh")]:
            raise PermissionError("helper is not executable")
        return original_run(args, **kwargs)

    monkeypatch.setattr(image_prefix.subprocess, "run", flaky_run)

    assert image_prefix.get_default_image_prefix(caller) == "ghcr.io/myorg/my-repo/images"


def test_get_image_prefix_honors_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_PREFIX", "registry.internal:5000/acme/repo/images/")

    assert image_prefix.get_image_prefix(script_path=__file__) == "registry.internal:5000/acme/repo/images"


def test_get_image_prefix_lowercases_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_PREFIX", "ghcr.io/MyOrg/MyRepo/Images")

    assert image_prefix.get_image_prefix(script_path=__file__) == "ghcr.io/myorg/myrepo/images"


def test_default_image_prefix_script_preserves_registry_port(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)

    helper = scripts_dir / "default-image-prefix.sh"
    helper.write_text(DEFAULT_IMAGE_PREFIX_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    helper.chmod(0o755)

    answers = repo_root / ".copier-answers.yml"
    answers.write_text("image_prefix: registry.internal:5000/acme/repo/images\n", encoding="utf-8")

    result = subprocess.run([str(helper)], check=True, capture_output=True, cwd=repo_root, text=True)

    assert result.stdout.strip() == "registry.internal:5000/acme/repo/images"


def test_default_image_prefix_script_normalizes_answer_prefix_segments(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)

    helper = scripts_dir / "default-image-prefix.sh"
    helper.write_text(DEFAULT_IMAGE_PREFIX_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    helper.chmod(0o755)

    answers = repo_root / ".copier-answers.yml"
    answers.write_text('image_prefix: "registry.internal:5000/Acme/Repo_Images"\n', encoding="utf-8")

    result = subprocess.run([str(helper)], check=True, capture_output=True, cwd=repo_root, text=True)

    assert result.stdout.strip() == "registry.internal:5000/acme/repo-images"


def test_default_image_prefix_script_uses_legacy_docker_org_answer(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)

    helper = scripts_dir / "default-image-prefix.sh"
    helper.write_text(DEFAULT_IMAGE_PREFIX_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    helper.chmod(0o755)

    answers = repo_root / ".copier-answers.yml"
    answers.write_text("docker_org: kamiwazaai\n", encoding="utf-8")

    result = subprocess.run([str(helper)], check=True, capture_output=True, cwd=repo_root, text=True)

    assert result.stdout.strip() == "kamiwazaai"


def test_default_image_prefix_script_uses_legacy_organization_answer(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)

    helper = scripts_dir / "default-image-prefix.sh"
    helper.write_text(DEFAULT_IMAGE_PREFIX_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    helper.chmod(0o755)

    answers = repo_root / ".copier-answers.yml"
    answers.write_text("organization: ghcr.io/legacy-org/legacy-repo/images\n", encoding="utf-8")

    result = subprocess.run([str(helper)], check=True, capture_output=True, cwd=repo_root, text=True)

    assert result.stdout.strip() == "ghcr.io/legacy-org/legacy-repo/images"


def test_default_image_prefix_script_normalizes_git_remote_names(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)

    helper = scripts_dir / "default-image-prefix.sh"
    helper.write_text(DEFAULT_IMAGE_PREFIX_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    helper.chmod(0o755)

    subprocess.run(["git", "init"], check=True, cwd=repo_root, capture_output=True, text=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:MyOrg/My_Repo.git"],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    result = subprocess.run([str(helper)], check=True, capture_output=True, cwd=repo_root, text=True)

    assert result.stdout.strip() == "ghcr.io/myorg/my-repo/images"


def test_default_image_prefix_script_handles_authenticated_https_remote(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)

    helper = scripts_dir / "default-image-prefix.sh"
    helper.write_text(DEFAULT_IMAGE_PREFIX_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    helper.chmod(0o755)

    subprocess.run(["git", "init"], check=True, cwd=repo_root, capture_output=True, text=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://x-access-token:ghp_token@github.com/MyOrg/My_Repo.git"],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    result = subprocess.run([str(helper)], check=True, capture_output=True, cwd=repo_root, text=True)

    assert result.stdout.strip() == "ghcr.io/myorg/my-repo/images"


def test_default_image_prefix_script_handles_ssh_remote_with_port(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)

    helper = scripts_dir / "default-image-prefix.sh"
    helper.write_text(DEFAULT_IMAGE_PREFIX_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    helper.chmod(0o755)

    subprocess.run(["git", "init"], check=True, cwd=repo_root, capture_output=True, text=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "ssh://git@github.com:22/MyOrg/My_Repo.git"],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    result = subprocess.run([str(helper)], check=True, capture_output=True, cwd=repo_root, text=True)

    assert result.stdout.strip() == "ghcr.io/myorg/my-repo/images"


def test_default_image_prefix_script_handles_git_plus_https_remote(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)

    helper = scripts_dir / "default-image-prefix.sh"
    helper.write_text(DEFAULT_IMAGE_PREFIX_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    helper.chmod(0o755)

    subprocess.run(["git", "init"], check=True, cwd=repo_root, capture_output=True, text=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git+https://github.com/MyOrg/My_Repo.git"],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    result = subprocess.run([str(helper)], check=True, capture_output=True, cwd=repo_root, text=True)

    assert result.stdout.strip() == "ghcr.io/myorg/my-repo/images"


def test_default_image_prefix_script_handles_trailing_slash_remote(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)

    helper = scripts_dir / "default-image-prefix.sh"
    helper.write_text(DEFAULT_IMAGE_PREFIX_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    helper.chmod(0o755)

    subprocess.run(["git", "init"], check=True, cwd=repo_root, capture_output=True, text=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/MyOrg/My_Repo.git/"],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    result = subprocess.run([str(helper)], check=True, capture_output=True, cwd=repo_root, text=True)

    assert result.stdout.strip() == "ghcr.io/myorg/my-repo/images"


def test_default_image_prefix_script_ignores_non_github_remote(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)

    helper = scripts_dir / "default-image-prefix.sh"
    helper.write_text(DEFAULT_IMAGE_PREFIX_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    helper.chmod(0o755)

    subprocess.run(["git", "init"], check=True, cwd=repo_root, capture_output=True, text=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://gitlab.com/MyOrg/My_Repo.git"],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    result = subprocess.run([str(helper)], check=True, capture_output=True, cwd=repo_root, text=True)

    assert result.stdout.strip() == "ghcr.io/kamiwaza-internal/demo-repo/images"
