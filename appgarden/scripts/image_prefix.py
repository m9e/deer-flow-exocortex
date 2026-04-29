"""Shared IMAGE_PREFIX resolution helpers for template scripts."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

DEFAULT_GITHUB_ORG = "kamiwaza-internal"
_COPIER_COMMENT_PATTERN = re.compile(r"\s+#.*$")
_GITHUB_REMOTE_PATTERNS = (
    re.compile(r"^git@github\.com:([^/]+)/([^/]+)$"),
    re.compile(r"^ssh://git@github\.com(?::\d+)?/([^/]+)/([^/]+)$"),
    re.compile(r"^(?:git\+)?https?://(?:[^@/]+@)?github\.com/([^/]+)/([^/]+)$"),
)


def _repo_root_for(script_path: str | Path | None = None) -> Path:
    if script_path is None:
        return Path(__file__).resolve().parents[1]
    return Path(script_path).resolve().parents[1]


def _normalize_name(value: str) -> str:
    return value.strip().lower().replace(" ", "-").replace("_", "-")


def _normalize_prefix(prefix: str) -> str:
    return "/".join(_normalize_name(segment) for segment in prefix.rstrip("/").split("/"))


def _strip_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return stripped


def _read_copier_value(repo_root: Path, key: str) -> str | None:
    answers_file = repo_root / ".copier-answers.yml"
    if not answers_file.exists():
        return None

    for line in answers_file.read_text(encoding="utf-8").splitlines():
        if not line.startswith(f"{key}:"):
            continue
        raw_value = line[len(key) + 1 :].lstrip()
        raw_value = _COPIER_COMMENT_PATTERN.sub("", raw_value).rstrip()
        if not raw_value:
            return None
        return _strip_quotes(raw_value)

    return None


def _read_git_remote(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "config", "--get", "remote.origin.url"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    remote_url = result.stdout.strip()
    if result.returncode != 0 or not remote_url:
        return None

    remote_url = remote_url.rstrip("/")
    if remote_url.endswith(".git"):
        remote_url = remote_url[:-4]

    for pattern in _GITHUB_REMOTE_PATTERNS:
        match = pattern.match(remote_url)
        if match is not None:
            owner, repo = match.groups()
            return f"{owner}/{repo}"

    return None


def _fallback_prefix_from_context(repo_root: Path) -> str:
    image_prefix = _read_copier_value(repo_root, "image_prefix")
    if image_prefix:
        return _normalize_prefix(image_prefix)

    legacy_prefix = _read_copier_value(repo_root, "docker_org") or _read_copier_value(repo_root, "organization")
    if legacy_prefix:
        return _normalize_prefix(legacy_prefix)

    github_org = _read_copier_value(repo_root, "github_org")
    repo_name = repo_root.name
    remote_ref = _read_git_remote(repo_root)
    if remote_ref:
        if not github_org:
            github_org = remote_ref.split("/", 1)[0]
        repo_name = remote_ref.rsplit("/", 1)[-1]

    normalized_org = _normalize_name(github_org or DEFAULT_GITHUB_ORG)
    normalized_repo = _normalize_name(repo_name)
    return f"ghcr.io/{normalized_org}/{normalized_repo}/images"


def _fallback_prefix(repo_root: Path) -> str:
    return _normalize_prefix(f"ghcr.io/{DEFAULT_GITHUB_ORG}/{repo_root.name}/images")


@lru_cache(maxsize=None)
def get_default_image_prefix(script_path: str | Path | None = None) -> str:
    """Return the repo-scoped GHCR default for the current repository."""
    repo_root = _repo_root_for(script_path)
    helper = repo_root / "scripts" / "default-image-prefix.sh"

    try:
        result = subprocess.run(
            [str(helper)],
            check=True,
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        sys.stderr.write(
            f"warning: failed to resolve IMAGE_PREFIX via {helper.name} ({exc}); "
            "falling back to inferred repo context\n"
        )
        return _fallback_prefix_from_context(repo_root)

    prefix = result.stdout.strip()
    if prefix:
        return _normalize_prefix(prefix)

    return _fallback_prefix_from_context(repo_root)


def get_image_prefix(
    env_var: str = "IMAGE_PREFIX",
    script_path: str | Path | None = None,
) -> str:
    """Return IMAGE_PREFIX from the environment or the repo-scoped GHCR default."""
    configured = os.getenv(env_var, "").strip()
    if configured:
        # Lowercase to match default-path resolution; OCI image refs are case-sensitive
        # and registries reject uppercase, so users pasting `ghcr.io/MyOrg/...` would
        # otherwise fail downstream with an opaque validation error.
        return configured.rstrip("/").lower()

    return get_default_image_prefix(script_path)
