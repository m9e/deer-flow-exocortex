"""Regression tests for kind-load-images.sh."""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "kind-load-images.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_kind_load_uses_normalized_reference_for_local_images(tmp_path):
    repo_root = tmp_path / "repo"
    script_dir = repo_root / "scripts"
    script_dir.mkdir(parents=True)
    copied_script = script_dir / "kind-load-images.sh"
    shutil.copy2(SCRIPT_PATH, copied_script)
    copied_script.chmod(copied_script.stat().st_mode | stat.S_IXUSR)

    (repo_root / ".repo-version").write_text("3\n")

    images_dir = repo_root / "build" / "kamiwaza-extension-registry" / "garden" / "v3" / "docker-images"
    images_dir.mkdir(parents=True)
    manifest = {
        "images": {
            "kamiwazaai/demo:1.0.0-dev": {
                "exists_locally": True,
                "export": {"success": False, "file": ""},
            }
        }
    }
    (images_dir / "manifest.json").write_text(json.dumps(manifest))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "commands.log"

    docker_script = f"""#!/bin/sh
set -eu
LOG_FILE="{log_path}"
printf 'docker %s\\n' "$*" >> "$LOG_FILE"

if [ "$1" = "exec" ] && [ "$2" = "kamiwaza-dev-control-plane" ] && [ "$3" = "true" ]; then
  exit 0
fi

if [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
  if [ "$3" = "kamiwazaai/demo:1.0.0-dev" ]; then
    exit 0
  fi
  exit 1
fi

if [ "$1" = "tag" ] && [ "$2" = "kamiwazaai/demo:1.0.0-dev" ] && [ "$3" = "docker.io/kamiwazaai/demo:1.0.0-dev" ]; then
  exit 0
fi

exit 1
"""
    _write_executable(bin_dir / "docker", docker_script)

    kind_script = f"""#!/bin/sh
set -eu
LOG_FILE="{log_path}"
printf 'kind %s\\n' "$*" >> "$LOG_FILE"

if [ "$1" = "get" ] && [ "$2" = "clusters" ]; then
  printf 'kamiwaza-dev\\n'
  exit 0
fi

if [ "$1" = "load" ] && [ "$2" = "docker-image" ] && [ "$3" = "docker.io/kamiwazaai/demo:1.0.0-dev" ] && [ "$4" = "--name" ] && [ "$5" = "kamiwaza-dev" ]; then
  exit 0
fi

exit 1
"""
    _write_executable(bin_dir / "kind", kind_script)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        [str(copied_script), "--repo-version", "3", "--cluster", "kamiwaza-dev"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr

    log_lines = log_path.read_text().splitlines()
    assert "docker image inspect kamiwazaai/demo:1.0.0-dev" in log_lines
    assert "docker image inspect docker.io/kamiwazaai/demo:1.0.0-dev" in log_lines
    assert "docker tag kamiwazaai/demo:1.0.0-dev docker.io/kamiwazaai/demo:1.0.0-dev" in log_lines
    assert "kind load docker-image docker.io/kamiwazaai/demo:1.0.0-dev --name kamiwaza-dev" in log_lines


def test_kind_load_warns_when_tar_repotags_cannot_be_read(tmp_path):
    repo_root = tmp_path / "repo"
    script_dir = repo_root / "scripts"
    script_dir.mkdir(parents=True)
    copied_script = script_dir / "kind-load-images.sh"
    shutil.copy2(SCRIPT_PATH, copied_script)
    copied_script.chmod(copied_script.stat().st_mode | stat.S_IXUSR)

    (repo_root / ".repo-version").write_text("3\n")

    images_dir = repo_root / "build" / "kamiwaza-extension-registry" / "garden" / "v3" / "docker-images"
    images_dir.mkdir(parents=True)
    manifest = {
        "images": {
            "kamiwazaai/demo:1.0.0-dev": {
                "exists_locally": True,
                "export": {"success": True, "file": "broken.tar"},
            }
        }
    }
    (images_dir / "manifest.json").write_text(json.dumps(manifest))
    (images_dir / "broken.tar").write_text("not a tar archive")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    docker_script = """#!/bin/sh
set -eu

if [ "$1" = "exec" ] && [ "$2" = "kamiwaza-dev-control-plane" ] && [ "$3" = "true" ]; then
  exit 0
fi

if [ "$1" = "exec" ] && [ "$2" = "-i" ] && [ "$3" = "kamiwaza-dev-control-plane" ] && [ "$4" = "ctr" ] && [ "$7" = "images" ] && [ "$8" = "import" ]; then
  exit 0
fi

if [ "$1" = "exec" ] && [ "$2" = "kamiwaza-dev-control-plane" ] && [ "$3" = "ctr" ] && [ "$6" = "images" ] && [ "$7" = "ls" ]; then
  exit 0
fi

exit 1
"""
    _write_executable(bin_dir / "docker", docker_script)

    kind_script = """#!/bin/sh
set -eu

if [ "$1" = "get" ] && [ "$2" = "clusters" ]; then
  printf 'kamiwaza-dev\n'
  exit 0
fi

exit 1
"""
    _write_executable(bin_dir / "kind", kind_script)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        [str(copied_script), "--repo-version", "3", "--cluster", "kamiwaza-dev"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Warning: Failed to read RepoTags from" in result.stderr
