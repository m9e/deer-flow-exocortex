#!/usr/bin/env python3
"""
Export Docker images from the registry for offline distribution.

This script reads the apps.json and tools.json registry files, collects all
unique Docker images (apps/services in apps.json, tools in tools.json), and
exports them as tar files for offline use.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_cached_docker_env: dict[str, str] | None = None


def _docker_env() -> dict[str, str]:
    """Return env for docker CLI calls, honoring DOCKER_CONTEXT over stale DOCKER_HOST."""
    global _cached_docker_env
    if _cached_docker_env is None:
        _cached_docker_env = os.environ.copy()
        if _cached_docker_env.get("DOCKER_CONTEXT"):
            _cached_docker_env.pop("DOCKER_HOST", None)
    return _cached_docker_env


def load_registry_files(registry_dir: Path) -> tuple[list, list]:
    """Load apps/services and tools from registry JSON files."""
    apps_file = registry_dir / "apps.json"
    tools_file = registry_dir / "tools.json"

    apps = []
    tools = []

    if apps_file.exists():
        with open(apps_file) as f:
            apps = json.load(f)
    else:
        print(f"Warning: {apps_file} not found")

    if tools_file.exists():
        with open(tools_file) as f:
            tools = json.load(f)
    else:
        print(f"Warning: {tools_file} not found")

    return apps, tools


def collect_unique_images(apps: list[dict], tools: list[dict]) -> set[str]:
    """Collect all unique Docker images from apps/services and tools."""
    images = set()

    # Collect from apps
    for app in apps:
        if app.get("docker_images"):
            images.update(app["docker_images"])

    # Collect from tools
    for tool in tools:
        if tool.get("docker_images"):
            images.update(tool["docker_images"])

    return images


def sanitize_filename(image_name: str) -> str:
    """Convert Docker image name to safe filename."""
    # Replace special characters with underscores
    # e.g., "ghcr.io/kamiwaza-outcome/appgarden-ai-chatbot:v2.1.2" -> "ghcr.io_kamiwaza-outcome_appgarden-ai-chatbot_v2.1.2.tar"
    filename = image_name.replace("/", "_").replace(":", "_")
    return f"{filename}.tar"


def check_image_exists(image: str) -> bool:
    """Check if Docker image exists locally."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            env=_docker_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Error checking image {image}: {e}")
        return False


def get_image_size(image: str) -> dict[str, Any]:
    """Get size information for a Docker image."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{.Size}}"],
            env=_docker_env(),
            capture_output=True,
            text=True,
            check=True,
        )
        size_bytes = int(result.stdout.strip())

        # Get compressed size estimate (roughly 1/3 of uncompressed for typical images)
        # This is an estimate; actual tar size will be calculated after export
        compressed_estimate = size_bytes // 3

        return {
            "uncompressed": size_bytes,
            "compressed_estimate": compressed_estimate,
            "human_readable": format_bytes(size_bytes),
        }
    except Exception as e:
        print(f"Warning: Could not get size for {image}: {e}")
        return {
            "uncompressed": 0,
            "compressed_estimate": 0,
            "human_readable": "unknown",
        }


def format_bytes(bytes_value: int | float) -> str:
    """Format bytes into human-readable string."""
    value = float(bytes_value)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024.0:
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{value:.1f}TB"


def export_image(image: str, output_path: Path) -> dict[str, Any]:
    """Export a Docker image to a tar file."""
    print(f"  Exporting {image}...")

    try:
        # Run docker save
        subprocess.run(
            ["docker", "save", "-o", str(output_path), image],
            env=_docker_env(),
            capture_output=True,
            text=True,
            check=True,
        )

        # Get actual file size
        file_size = output_path.stat().st_size

        # Calculate SHA256 checksum
        sha256 = calculate_sha256(output_path)

        return {
            "success": True,
            "file": output_path.name,
            "size": file_size,
            "human_readable_size": format_bytes(file_size),
            "sha256": sha256,
        }
    except subprocess.CalledProcessError as e:
        print(f"  ERROR: Failed to export {image}: {e.stderr}")
        return {"success": False, "error": str(e.stderr)}
    except Exception as e:
        print(f"  ERROR: Failed to export {image}: {e}")
        return {"success": False, "error": str(e)}


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def pull_image(image: str) -> bool:
    """Attempt to pull a Docker image."""
    print(f"  Attempting to pull {image}...")
    try:
        subprocess.run(["docker", "pull", image], env=_docker_env(), capture_output=True, text=True, check=True)
        print(f"  Successfully pulled {image}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  WARNING: Could not pull {image}: {e.stderr}")
        return False


def create_manifest(images_data: dict[str, dict], output_dir: Path) -> None:
    """Create a manifest.json with image metadata."""
    manifest_path = output_dir / "manifest.json"

    manifest = {
        "version": "1.0.0",
        "images": images_data,
        "total_images": len(images_data),
        "total_size": sum(
            img["export"]["size"] for img in images_data.values() if img.get("export", {}).get("success", False)
        ),
    }

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nCreated manifest: {manifest_path}")


def get_garden_dir_name(repo_version: str) -> str:
    """Map REPO_VERSION to directory name: 1 → 'default', everything else → 'v{N}'."""
    return "default" if repo_version == "1" else f"v{repo_version}"


def get_repo_version() -> str:
    """Get repository format version from CLI args or environment, defaulting to 2."""
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--repo-version",
        default=os.environ.get("REPO_VERSION", "2"),
        help="Repository format version: 2 (default), 3 (K8s), or 1 (legacy)",
    )
    args, _ = parser.parse_known_args()
    return args.repo_version


def main():
    """Main entry point."""
    # Check for non-interactive mode
    non_interactive = "--non-interactive" in sys.argv or "--auto" in sys.argv

    # Get repo version and map to directory name
    repo_version = get_repo_version()
    garden_dir_name = get_garden_dir_name(repo_version)

    # Get paths
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    registry_root = repo_root / "build" / "kamiwaza-extension-registry"
    registry_dir = registry_root / "garden" / garden_dir_name

    # Check if registry exists
    if not registry_dir.exists():
        print(f"Error: Registry not found at {registry_dir}. Run build-registry.py first.")
        sys.exit(1)

    # Create docker-images directory
    images_dir = registry_dir / "docker-images"
    images_dir.mkdir(parents=True, exist_ok=True)

    print("Docker Image Export Tool")
    print("=" * 50)

    # Load registry files
    print("\nLoading registry files...")
    apps, tools = load_registry_files(registry_dir)
    print(f"  Found {len(apps)} apps/services and {len(tools)} tools")

    # Collect unique images
    print("\nCollecting unique images...")
    unique_images = collect_unique_images(apps, tools)
    print(f"  Found {len(unique_images)} unique images")

    if not unique_images:
        print("No images to export.")
        return

    # Process each image
    images_data = {}
    missing_images = []

    print("\nChecking image availability...")
    for image in sorted(unique_images):
        image_info = {
            "name": image,
            "exists_locally": check_image_exists(image),
            "size_info": get_image_size(image) if check_image_exists(image) else None,
        }

        if not image_info["exists_locally"]:
            missing_images.append(image)
            print(f"  ⚠ {image} - NOT FOUND locally")
        else:
            size_info: dict[str, Any] | None = image_info.get("size_info")  # type: ignore[assignment]
            if size_info is not None:
                size = size_info["human_readable"]
                print(f"  ✓ {image} - {size}")

        images_data[image] = image_info

    # Handle missing images
    if missing_images:
        print(f"\nWarning: {len(missing_images)} images not found locally")
        if non_interactive:
            print("  Skipping missing images (non-interactive mode)")
        else:
            response = input("Attempt to pull missing images? (y/n): ").lower()
            if response == "y":
                for image in missing_images:
                    if pull_image(image):
                        images_data[image]["exists_locally"] = True
                        images_data[image]["size_info"] = get_image_size(image)

    # Export images
    print(f"\nExporting images to {images_dir}...")
    export_count = 0
    skip_count = 0
    total_size = 0

    for image in sorted(unique_images):
        if not images_data[image]["exists_locally"]:
            print(f"  SKIPPING {image} - not available")
            skip_count += 1
            continue

        output_file = images_dir / sanitize_filename(image)

        # Check if already exported
        if output_file.exists():
            if non_interactive:
                print(f"  Overwriting existing {output_file.name}")
            else:
                response = input(f"  {output_file.name} exists. Overwrite? (y/n): ").lower()
                if response != "y":
                    print(f"  SKIPPING {image}")
                    skip_count += 1
                    continue

        export_result = export_image(image, output_file)
        images_data[image]["export"] = export_result

        if export_result["success"]:
            export_count += 1
            total_size += export_result["size"]
            print(f"    Saved: {export_result['file']} ({export_result['human_readable_size']})")
            print(f"    SHA256: {export_result['sha256']}")
        else:
            skip_count += 1

    # Create manifest
    create_manifest(images_data, images_dir)

    # Summary
    print("\n" + "=" * 50)
    print("Export Summary:")
    print(f"  Total images: {len(unique_images)}")
    print(f"  Exported: {export_count}")
    print(f"  Skipped: {skip_count}")
    print(f"  Total size: {format_bytes(total_size)}")
    print(f"  Output directory: {images_dir}")

    # Create import script
    create_import_script(images_dir)
    print(f"\nCreated import script: {images_dir / 'import-images.sh'}")
    print("To import images on another machine, copy the docker-images directory and run:")
    print("  cd docker-images && ./import-images.sh")


def create_import_script(images_dir: Path) -> None:
    """Create a shell script to import the exported images."""
    script_content = """#!/bin/bash
# Import Docker images from tar files
# Generated by export-images.py

set -e

echo "Docker Image Import Tool"
echo "========================"
echo ""

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed or not in PATH"
    exit 1
fi

# Count tar files
TAR_COUNT=$(ls -1 *.tar 2>/dev/null | wc -l)

if [ "$TAR_COUNT" -eq 0 ]; then
    echo "No tar files found in current directory"
    exit 1
fi

echo "Found $TAR_COUNT image tar files"
echo ""

# Import each tar file
SUCCESS=0
FAILED=0

for tar_file in *.tar; do
    echo "Importing $tar_file..."
    if docker load -i "$tar_file"; then
        echo "  ✓ Success"
        SUCCESS=$((SUCCESS + 1))
    else
        echo "  ✗ Failed"
        FAILED=$((FAILED + 1))
    fi
    echo ""
done

# Summary
echo "========================"
echo "Import Summary:"
echo "  Success: $SUCCESS"
echo "  Failed: $FAILED"

if [ "$FAILED" -gt 0 ]; then
    exit 1
fi
"""

    script_path = images_dir / "import-images.sh"
    with open(script_path, "w") as f:
        f.write(script_content)

    # Make executable
    os.chmod(script_path, 0o755)


if __name__ == "__main__":
    main()
