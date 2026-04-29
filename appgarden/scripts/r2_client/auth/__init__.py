"""Authentication resolution chain for r2-client."""

from r2_client.auth.chain import resolve_credentials
from r2_client.auth.credentials import Credentials
from r2_client.auth.provider import CredentialProvider
from r2_client.auth.static import StaticCredentialProvider

__all__ = [
    "CredentialProvider",
    "Credentials",
    "StaticCredentialProvider",
    "resolve_credentials",
]
