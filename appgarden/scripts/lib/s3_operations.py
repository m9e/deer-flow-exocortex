"""S3/R2 operations for registry management.

Provides download, upload, and locking functionality for the extension registry.
Uses r2-client for R2/S3 access (Cloudflare auth or static credentials).
"""

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

from botocore.exceptions import ClientError
from r2_client import get_client


def get_s3_endpoint() -> str | None:
    """Get the S3 endpoint URL from environment."""
    endpoint = os.getenv("KAMIWAZA_REGISTRY_ENDPOINT")
    if not endpoint:
        # Check for R2 account ID to construct endpoint
        account_id = os.getenv("KAMIWAZA_REGISTRY_ACCOUNT_ID")
        if account_id:
            endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    return endpoint


def configure_aws_profile(stage: str) -> str | None:
    """Optionally set AWS_PROFILE from per-stage env var for registry operations.

    Primary auth is r2-client (SSO or R2_* env vars). Profiles in ~/.aws/credentials
    are for user overrides and service principals only.
    """
    stage_upper = stage.upper()
    stage_profile = os.getenv(f"AWS_PROFILE_{stage_upper}")
    if stage_profile:
        os.environ["AWS_PROFILE"] = stage_profile
    return stage_profile


def get_bucket_for_stage(stage: str) -> str:
    """Get the bucket name for the given stage."""
    configure_aws_profile(stage)
    stage_upper = stage.upper()
    bucket = os.getenv(f"KAMIWAZA_REGISTRY_BUCKET_{stage_upper}")
    if not bucket:
        bucket = os.getenv("KAMIWAZA_REGISTRY_BUCKET")
    if not bucket:
        raise ValueError(
            f"No bucket configured for stage '{stage}'. "
            f"Set KAMIWAZA_REGISTRY_BUCKET_{stage_upper} or KAMIWAZA_REGISTRY_BUCKET"
        )
    return bucket


_S3_CLIENT_CACHE: dict[str, object] = {}
_CACHE_MAX_SIZE = 8


def _get_s3_client(bucket: str):
    """Get r2-client S3 client for the given bucket (cached per bucket)."""
    if bucket in _S3_CLIENT_CACHE:
        return _S3_CLIENT_CACHE[bucket]
    endpoint = get_s3_endpoint()
    region = os.getenv("KAMIWAZA_REGISTRY_REGION")
    if region is None:
        region = "auto" if endpoint else "us-east-1"
    client = get_client(
        endpoint_url=endpoint or None,
        region_name=region,
        bucket=bucket,
    )
    if len(_S3_CLIENT_CACHE) >= _CACHE_MAX_SIZE:
        _S3_CLIENT_CACHE.clear()
    _S3_CLIENT_CACHE[bucket] = client
    return client


def s3_path(bucket: str, path: str) -> str:
    """Construct an S3 path."""
    path = path.lstrip("/")
    return f"s3://{bucket}/{path}"


def _lock_key(bucket: str, garden_dir: str | None = None) -> str:
    """Get the S3 object key for the registry lock file."""
    lock_path = lock_s3_path(bucket, garden_dir)
    return lock_path.replace(f"s3://{bucket}/", "")


def lock_s3_path(bucket: str, garden_dir: str | None = None) -> str:
    """Construct the S3 path for the registry lock file."""
    lock_name = os.getenv("KAMIWAZA_REGISTRY_LOCK_NAME", "registry.lock")
    if garden_dir:
        return s3_path(bucket, f"garden/{garden_dir}/{lock_name}")
    return s3_path(bucket, lock_name)


def check_lock_exists(bucket: str, garden_dir: str | None = None) -> bool:
    """Check if a lock file exists in the bucket."""
    s3 = _get_s3_client(bucket)
    key = _lock_key(bucket, garden_dir)
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def get_lock_info(bucket: str, garden_dir: str | None = None) -> dict | None:
    """Get lock file contents if it exists."""
    if not check_lock_exists(bucket, garden_dir):
        return None

    s3 = _get_s3_client(bucket)
    key = _lock_key(bucket, garden_dir)
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read().decode()
    except ClientError:
        return None

    try:
        data: dict = json.loads(body)
        return data
    except json.JSONDecodeError:
        return {"raw": body}


def acquire_lock(bucket: str, garden_dir: str | None = None, owner: str | None = None) -> bool:
    """Acquire a lock on the registry bucket.

    Uses atomic conditional put (IfNoneMatch='*') to avoid TOCTOU races between
    concurrent publishers. Requires S3-compatible backend that supports conditional writes.

    Args:
        bucket: S3 bucket name
        garden_dir: Optional garden directory to scope the lock
        owner: Optional owner identifier (defaults to CI job ID or hostname)

    Returns:
        True if lock acquired

    Raises:
        RuntimeError if lock exists (with details about existing lock)
    """
    if owner is None:
        owner = os.getenv("CI_JOB_ID") or os.getenv("GITHUB_RUN_ID") or "manual"

    lock_content = {
        "owner": owner,
        "hostname": socket.gethostname(),
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
    }
    lock_json = json.dumps(lock_content, indent=2)
    lock_path = lock_s3_path(bucket, garden_dir)
    lock_key = _lock_key(bucket, garden_dir)

    s3 = _get_s3_client(bucket)
    try:
        s3.put_object(
            Bucket=bucket,
            Key=lock_key,
            Body=lock_json.encode(),
            IfNoneMatch="*",
        )
    except ClientError as e:
        code = e.response["Error"].get("Code", "")
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        if code in ("412", "409", "PreconditionFailed", "ConditionalCheckFailed", "Conflict") or status in (412, 409):
            existing_lock = get_lock_info(bucket, garden_dir)
            raise RuntimeError(
                f"Lock already exists in bucket '{bucket}' (concurrent publish).\n"
                f"Lock info: {json.dumps(existing_lock or {}, indent=2)}\n"
                f"Remove lock with: make remove-publish-lock STAGE=<stage>"
            ) from e
        raise RuntimeError(f"Failed to create lock: {e.response['Error'].get('Message', str(e))}") from e

    print(f"Lock acquired: {lock_path}")
    return True


def release_lock(bucket: str, garden_dir: str | None = None) -> bool:
    """Release the lock on the registry bucket.

    Args:
        bucket: S3 bucket name
        garden_dir: Optional garden directory to scope the lock

    Returns:
        True if lock released, False if no lock existed
    """
    if not check_lock_exists(bucket, garden_dir):
        print("No lock to release")
        return False

    lock_path = lock_s3_path(bucket, garden_dir)
    lock_key = _lock_key(bucket, garden_dir)
    s3 = _get_s3_client(bucket)

    try:
        s3.delete_object(Bucket=bucket, Key=lock_key)
        print(f"Lock released: {lock_path}")
        return True
    except ClientError as e:
        print(f"Warning: Failed to release lock: {e.response['Error'].get('Message', str(e))}")
        return False


def _sync_down(bucket: str, prefix: str, local_dir: Path, s3) -> None:
    """Download all objects with prefix to local directory."""
    local_dir_resolved = local_dir.resolve()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            rel_path = key[len(prefix) :].lstrip("/")
            if ".." in rel_path or rel_path.startswith("/"):
                raise ValueError(f"Rejected path traversal in S3 key: {key}")
            local_file = (local_dir / rel_path).resolve()
            if not str(local_file).startswith(str(local_dir_resolved)):
                raise ValueError(f"Path traversal blocked: {key} would write outside {local_dir}")
            local_file.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(local_file))


def download_registry(
    bucket: str, garden_dir: str, local_path: Path, create_backup: bool = True
) -> tuple[Path, Path | None]:
    """Download the registry from S3.

    Args:
        bucket: S3 bucket name
        garden_dir: Garden directory name (e.g. "v2", "v3", or "default")
        local_path: Local path to download to
        create_backup: Whether to create a timestamped backup

    Returns:
        Tuple of (working_path, backup_path)
    """
    remote_path = s3_path(bucket, f"garden/{garden_dir}/")
    working_path = local_path / "remote" / garden_dir
    backup_path = None

    # Create working directory
    working_path.mkdir(parents=True, exist_ok=True)

    prefix = f"garden/{garden_dir}/"
    s3 = _get_s3_client(bucket)
    print(f"Downloading registry from {remote_path}...")
    try:
        _sync_down(bucket, prefix, working_path, s3)
    except ClientError as e:
        code = e.response["Error"].get("Code", "")
        if code in ("NoSuchBucket", "NoSuchKey") or not str(e):
            print("Remote registry is empty (first publish)")
        else:
            raise RuntimeError(f"Failed to download registry: {e}") from e

    # Create backup if requested
    if create_backup:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = local_path / "backups" / garden_dir / timestamp
        backup_path.mkdir(parents=True, exist_ok=True)

        # Copy downloaded content to backup
        if working_path.exists() and any(working_path.iterdir()):
            import shutil

            shutil.copytree(working_path, backup_path, dirs_exist_ok=True)
            print(f"Backup created: {backup_path}")

    return working_path, backup_path


def _sync_up(bucket: str, prefix: str, local_dir: Path, s3, delete: bool) -> None:
    """Upload local directory to prefix; optionally delete remote objects not in local."""
    local_keys = set()
    for f in local_dir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(local_dir)
            key = f"{prefix}{rel.as_posix()}"
            local_keys.add(key)
            s3.upload_file(str(f), bucket, key)

    if delete:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key not in local_keys:
                    s3.delete_object(Bucket=bucket, Key=key)


def upload_registry(bucket: str, garden_dir: str, local_path: Path, delete: bool = True) -> bool:
    """Upload the registry to S3.

    Args:
        bucket: S3 bucket name
        garden_dir: Garden directory name (e.g. "v2", "v3", or "default")
        local_path: Local path containing the registry
        delete: Whether to delete remote files not in local

    Returns:
        True if upload succeeded
    """
    remote_path = s3_path(bucket, f"garden/{garden_dir}/")
    prefix = f"garden/{garden_dir}/"
    s3 = _get_s3_client(bucket)

    print(f"Uploading registry to {remote_path}...")
    _sync_up(bucket, prefix, local_path, s3, delete=delete)

    print(f"Registry uploaded to {remote_path}")
    return True


def restore_backup(bucket: str, garden_dir: str, backup_path: Path) -> bool:
    """Restore a backup to S3.

    Args:
        bucket: S3 bucket name
        garden_dir: Garden directory name (e.g. "v2", "v3", or "default")
        backup_path: Path to backup directory

    Returns:
        True if restore succeeded
    """
    if not backup_path.exists():
        raise ValueError(f"Backup path does not exist: {backup_path}")

    print(f"Restoring backup from {backup_path}...")
    return upload_registry(bucket, garden_dir, backup_path, delete=True)


def verify_upload(bucket: str, garden_dir: str, local_path: Path) -> bool:
    """Verify that the upload matches local state.

    Args:
        bucket: S3 bucket name
        garden_dir: Garden directory name
        local_path: Local path that was uploaded

    Returns:
        True if verification passed
    """
    import filecmp
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        verify_path = Path(tmpdir) / garden_dir
        verify_path.mkdir(parents=True)

        prefix = f"garden/{garden_dir}/"
        s3 = _get_s3_client(bucket)
        print("Verifying upload...")
        _sync_down(bucket, prefix, verify_path, s3)

        # Compare apps.json and tools.json
        for filename in ["apps.json", "tools.json"]:
            local_file = local_path / filename
            remote_file = verify_path / filename

            if local_file.exists() and remote_file.exists():
                if not filecmp.cmp(local_file, remote_file, shallow=False):
                    print(f"Verification failed: {filename} mismatch")
                    return False
            elif local_file.exists() != remote_file.exists():
                print(f"Verification failed: {filename} missing")
                return False

        print("Verification passed")
        return True


if __name__ == "__main__":
    # Simple test/debug functionality
    import argparse

    parser = argparse.ArgumentParser(description="S3 operations for registry")
    parser.add_argument("--stage", default="dev", help="Stage (dev/stage/prod)")
    parser.add_argument(
        "--garden-dir",
        default=None,
        help="Garden directory name (e.g., v2 or default) to scope locks",
    )
    parser.add_argument("--check-lock", action="store_true", help="Check if lock exists")
    parser.add_argument("--acquire-lock", action="store_true", help="Acquire lock")
    parser.add_argument("--release-lock", action="store_true", help="Release lock")

    args = parser.parse_args()
    bucket = get_bucket_for_stage(args.stage)

    if args.check_lock:
        lock_info = get_lock_info(bucket, args.garden_dir)
        if lock_info:
            print(f"Lock exists: {json.dumps(lock_info, indent=2)}")
        else:
            print("No lock found")
    elif args.acquire_lock:
        acquire_lock(bucket, args.garden_dir)
    elif args.release_lock:
        release_lock(bucket, args.garden_dir)
