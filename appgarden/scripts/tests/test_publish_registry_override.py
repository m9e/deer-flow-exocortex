"""Regression tests for publish-images registry override helpers."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "publish-images.sh"
REGISTRY_AUTH_LIB = SCRIPT_PATH.parent / "lib" / "registry-auth.sh"


def run_publish_helper_snippet(snippet: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        temp_script = tmp_path / "publish-images.sh"
        temp_lib_dir = tmp_path / "lib"
        temp_lib_dir.mkdir()
        temp_script.write_text(SCRIPT_PATH.read_text(encoding="utf-8").rsplit("\nmain\n", 1)[0] + "\n", encoding="utf-8")
        (temp_lib_dir / "registry-auth.sh").write_text(REGISTRY_AUTH_LIB.read_text(encoding="utf-8"), encoding="utf-8")

        command = (
            'IMAGE_PREFIX="ghcr.io/test-org/test-repo/images"; '
            f"source {temp_script} >/dev/null 2>&1; "
            + snippet
        )
        result = subprocess.run(
            ["bash", "-lc", command],
            check=True,
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        return result.stdout.strip()


def test_build_effective_image_name_replaces_existing_registry_host() -> None:
    output = run_publish_helper_snippet(
        'REGISTRY="mirror.example.com/"; '
        'printf "%s" "$(build_effective_image_name "ghcr.io/acme/repo/images/demo-app")"'
    )

    assert output == "mirror.example.com/acme/repo/images/demo-app"


def test_get_effective_registry_prefix_prefers_registry_override() -> None:
    output = run_publish_helper_snippet(
        'IMAGE_PREFIX="ghcr.io/acme/repo/images"; '
        'REGISTRY="mirror.example.com/team/"; '
        'printf "%s" "$(get_effective_registry_prefix)"'
    )

    assert output == "mirror.example.com/team"
