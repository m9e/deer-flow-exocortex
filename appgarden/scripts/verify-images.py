#!/usr/bin/env python3
"""
Verify Docker images referenced in extensions exist locally or in registry.

This script helps ensure that all Docker images referenced in extension metadata
and docker-compose files are available either locally or in a registry.
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml


class ImageVerifier:
    def __init__(self, local: bool = True, registry: bool = False, pull: bool = False):
        self.local = local
        self.registry = registry
        self.pull = pull
        self.missing_images: set[str] = set()
        self.verified_images: set[str] = set()
        self.errors: list[str] = []

    def verify_local_image(self, image: str) -> bool:
        """Check if image exists in local Docker daemon."""
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0
        except Exception as e:
            self.errors.append(f"Error checking local image {image}: {e}")
            return False

    def verify_registry_image(self, image: str) -> bool:
        """Check if image exists in Docker Hub registry."""
        # Parse image name
        parts = image.split(":")
        if len(parts) == 2:
            image_name, tag = parts
        else:
            image_name = parts[0]
            tag = "latest"

        # Handle official images vs user/org images
        if "/" not in image_name:
            image_name = f"library/{image_name}"

        # Docker Hub API endpoint
        url = f"https://hub.docker.com/v2/repositories/{image_name}/tags/{tag}"

        try:
            with urllib.request.urlopen(url) as response:
                return response.status == 200
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            self.errors.append(f"Error checking registry for {image}: {e}")
            return False
        except Exception as e:
            self.errors.append(f"Error checking registry for {image}: {e}")
            return False

    def pull_image(self, image: str) -> bool:
        """Pull image from registry."""
        try:
            print(f"  Pulling {image}...")
            result = subprocess.run(["docker", "pull", image], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                print(f"  ✅ Successfully pulled {image}")
                return True
            else:
                print(f"  ❌ Failed to pull {image}: {result.stderr}")
                return False
        except Exception as e:
            self.errors.append(f"Error pulling image {image}: {e}")
            return False

    def verify_image(self, image: str) -> tuple[bool, str]:
        """Verify image exists locally or in registry based on flags."""
        # Skip if already verified
        if image in self.verified_images:
            return True, "cached"

        found = False
        location = []

        # Check locally first if requested
        if self.local:
            if self.verify_local_image(image):
                found = True
                location.append("local")

        # Check registry if requested and not found locally
        if self.registry and not found:
            if self.verify_registry_image(image):
                found = True
                location.append("registry")

                # Pull if requested
                if self.pull and self.pull_image(image):
                    location.append("pulled")

        if found:
            self.verified_images.add(image)
            return True, "/".join(location)
        else:
            self.missing_images.add(image)
            return False, "not found"

    def extract_images_from_metadata(self, metadata_path: Path) -> list[str]:
        """Extract image references from kamiwaza.json."""
        images = []
        try:
            with open(metadata_path) as f:
                data = json.load(f)

            # Direct image reference (mainly for tools)
            if "image" in data:
                images.append(data["image"])

            return images
        except Exception as e:
            self.errors.append(f"Error reading {metadata_path}: {e}")
            return []

    def extract_images_from_compose(self, compose_path: Path) -> list[str]:
        """Extract image references from docker-compose files."""
        images = []
        try:
            with open(compose_path) as f:
                data = yaml.safe_load(f)

            if "services" in data:
                for _service_name, service in data["services"].items():
                    if "image" in service:
                        image = service["image"]
                        # Skip images with unexpanded variables
                        if not image.startswith("${"):
                            images.append(image)

            return images
        except Exception as e:
            self.errors.append(f"Error reading {compose_path}: {e}")
            return []

    def process_extension(self, ext_path: Path) -> dict[str, list[str]]:
        """Process a single extension and extract all image references."""
        images = []

        # Check metadata
        metadata_path = ext_path / "kamiwaza.json"
        if metadata_path.exists():
            images.extend(self.extract_images_from_metadata(metadata_path))

        # Check docker-compose files
        for compose_file in ["docker-compose.yml", "docker-compose.appgarden.yml"]:
            compose_path = ext_path / compose_file
            if compose_path.exists():
                images.extend(self.extract_images_from_compose(compose_path))

        return list(set(images))  # Remove duplicates

    def verify_all_extensions(self) -> bool:
        """Verify all extensions in the repository."""
        script_dir = Path(__file__).parent
        repo_root = script_dir.parent

        print("Verifying Docker images...")
        print(f"Mode: {'Local' if self.local else ''} {'Registry' if self.registry else ''}")
        print("=" * 50)

        all_success = True

        for ext_type in ["apps", "tools"]:
            type_dir = repo_root / ext_type
            if not type_dir.exists():
                continue

            print(f"\nVerifying {ext_type}...")

            for ext_path in sorted(type_dir.iterdir()):
                if not ext_path.is_dir():
                    continue

                images = self.process_extension(ext_path)
                if not images:
                    continue

                print(f"\n{ext_path.relative_to(repo_root)}:")

                for image in images:
                    found, location = self.verify_image(image)
                    if found:
                        print(f"  ✅ {image} ({location})")
                    else:
                        print(f"  ❌ {image} (not found)")
                        all_success = False

        print("\n" + "=" * 50)
        print("Summary:")
        print(f"  ✅ Verified: {len(self.verified_images)} images")
        print(f"  ❌ Missing: {len(self.missing_images)} images")

        if self.missing_images:
            print("\nMissing images:")
            for image in sorted(self.missing_images):
                print(f"  - {image}")

        if self.errors:
            print("\nErrors encountered:")
            for error in self.errors:
                print(f"  - {error}")

        return all_success and len(self.missing_images) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Verify Docker images for Kamiwaza extensions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default: Check local Docker daemon only
  %(prog)s

  # Check registry only
  %(prog)s --registry --no-local

  # Check both local and registry
  %(prog)s --local --registry

  # Pull missing images from registry
  %(prog)s --registry --pull
""",
    )

    parser.add_argument(
        "--local",
        action="store_true",
        default=True,
        help="Check local Docker daemon (default: True)",
    )
    parser.add_argument("--no-local", action="store_true", help="Disable local Docker daemon check")
    parser.add_argument("--registry", action="store_true", help="Check Docker Hub registry")
    parser.add_argument(
        "--pull",
        action="store_true",
        help="Pull images from registry if not found locally",
    )

    args = parser.parse_args()

    # Handle --no-local flag
    if args.no_local:
        args.local = False

    # Validate arguments
    if not args.local and not args.registry:
        parser.error("At least one of --local or --registry must be enabled")

    if args.pull and not args.registry:
        parser.error("--pull requires --registry")

    # Create verifier and run
    verifier = ImageVerifier(local=args.local, registry=args.registry, pull=args.pull)

    success = verifier.verify_all_extensions()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
