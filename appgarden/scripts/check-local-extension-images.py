#!/usr/bin/env python3
"""
Warn when an extension's deployment images from the generated registry are not
present locally for the expected tags.

This does not fail deployment; it only prints a warning so users can decide whether
to run `make build` before `make kamiwaza-push`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from image_prefix import get_image_prefix


def get_stage_registry_filename(ext_type: str) -> str:
    if ext_type == "tool":
        return "tools.json"
    return "apps.json"


def docker_cli_env() -> dict[str, str]:
    env = os.environ.copy()
    if env.get("DOCKER_CONTEXT"):
        env.pop("DOCKER_HOST", None)
    return env


def image_exists_local(image: str) -> bool:
    env = docker_cli_env()
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except FileNotFoundError:
        print("Warning: docker is not available on PATH; unable to verify local images.")
        return True
    return result.returncode == 0


def image_name_variants(image: str) -> Iterable[str]:
    yield image

    if "/" not in image or ":" not in image.split("/")[-1]:
        return

    name, tag = image.rsplit(":", 1)
    if tag.startswith("v") and len(tag) > 1:
        yield f"{name}:{tag[1:]}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--stage", default="dev")
    parser.add_argument("--repo-version", default="2")
    parser.add_argument("--image-prefix")
    args = parser.parse_args()

    ext_type = args.type
    ext_name = args.name
    repo_version = args.repo_version
    # Lowercase to match image_prefix.py:get_image_prefix normalization; registry
    # entries are written with the lowercased prefix, so a mixed-case CLI value
    # would silently fail the startswith() check at line 144.
    image_prefix = (args.image_prefix or get_image_prefix(script_path=__file__)).rstrip("/").lower()

    repo_root = Path(__file__).resolve().parent.parent
    garden_dir = "default" if repo_version == "1" else f"v{repo_version}"
    registry_file = (
        repo_root
        / "build"
        / "kamiwaza-extension-registry"
        / "garden"
        / garden_dir
        / get_stage_registry_filename(ext_type)
    )

    if not registry_file.exists():
        print(
            "Warning: Registry file not found for local image check: "
            f"{registry_file.relative_to(repo_root)}. Run `make build-registry` first."
        )
        return

    with registry_file.open() as f:
        entries = json.load(f)

    matching_entry = None
    for entry in entries:
        if entry.get("name") == ext_name:
            matching_entry = entry
            break

    if matching_entry is None:
        metadata_file = repo_root / f"{ext_type}s" / ext_name / "kamiwaza.json"
        if metadata_file.exists():
            try:
                with metadata_file.open() as f:
                    metadata = json.load(f)
                metadata_name = metadata.get("name")
                if metadata_name:
                    for entry in entries:
                        if entry.get("name") == metadata_name:
                            matching_entry = entry
                            break
            except Exception:
                logger.debug(
                    "Could not read metadata to match registry entry for %s/%s",
                    ext_type,
                    ext_name,
                    exc_info=True,
                )

    if matching_entry is None:
        print(
            f"Warning: Could not find registry entry for {ext_type}/{ext_name}; "
            "skipping local image availability check."
        )
        return

    images = matching_entry.get("docker_images", [])
    if not images:
        return

    missing_images: list[str] = []
    for image in images:
        if image_prefix and not image.startswith(f"{image_prefix}/"):
            continue
        if not any(image_exists_local(candidate) for candidate in image_name_variants(image)):
            missing_images.append(image)

    if not missing_images:
        return

    print(
        "Warning: Some registry images required for this push are not available locally "
        f"for {ext_type}/{ext_name} (stage={args.stage}):"
    )
    for image in missing_images:
        print(f"  - {image}")
    print(
        "\nSuggested fix: run "
        f"make build TYPE={ext_type} NAME={ext_name}"
        " [or make build-no-cache] to generate the expected local images before "
        "retrying."
    )


if __name__ == "__main__":
    main()
