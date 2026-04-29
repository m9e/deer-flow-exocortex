"""CLI/SDK adapters for r2-client."""

from r2_client.adapters.base import BaseAdapter
from r2_client.adapters.boto3 import Boto3Adapter
from r2_client.auth.credentials import Credentials

__all__ = ["BaseAdapter", "Boto3Adapter", "Credentials"]
