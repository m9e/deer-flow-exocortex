"""Cloudflare R2 client with transparent Cloudflare auth.

A drop-in replacement for boto3's S3 client for R2 buckets.
Vendored in extensions template (version tied to template).
"""

from r2_client.auth.credentials import Credentials
from r2_client.auth.provider import CredentialProvider
from r2_client.client import get_client, get_resource

__all__ = ["CredentialProvider", "Credentials", "get_client", "get_resource"]
