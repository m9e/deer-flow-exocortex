"""Credential provider — yields raw credentials for any adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from botocore.credentials import RefreshableCredentials

from r2_client.auth.chain import resolve_credentials
from r2_client.auth.credentials import Credentials
from r2_client.auth.sso import exchange_token_for_credentials, get_cloudflare_token
from r2_client.auth.static import StaticCredentials
from r2_client.config import Config

# Refresh R2 creds when they have less than this many seconds left
_REFRESH_BUFFER_SECONDS = 60


class CredentialProvider:
    """Provides raw credentials for any adapter (boto3, rclone, aws-cli, etc.).

    Handles both static and SSO flows. Adapters call get_credentials() and
    receive Credentials in a format they can consume.

    When bucket is set, SSO credentials are requested for that bucket.
    Useful when the user is in multiple groups and the default role-based
    bucket would be prod; pass bucket='dev-kevin-test' to get dev creds.
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        session_token: str | None = None,
        bucket: str | None = None,
    ) -> None:
        self._config = config or Config.load()
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._session_token = session_token
        self._bucket = bucket
        self._sso_cache: dict[str, Credentials] = {}  # keyed by bucket or "default"

    def get_credentials(self) -> Credentials:
        """Return credentials (static or SSO). Handles refresh for SSO."""
        static, method = resolve_credentials(
            access_key_id=self._access_key_id,
            secret_access_key=self._secret_access_key,
            session_token=self._session_token,
        )

        if method == "static" and static is not None:
            return self._static_to_credentials(static)

        return self._get_sso_credentials()

    def get_credentials_for_bucket(self, bucket: str) -> Credentials:
        """Return credentials for a specific bucket (SSO only).

        Use when managing multiple buckets: fetches or returns cached creds
        for the given bucket. Browser login happens once (JWT cached); per-bucket
        credential fetches use the cached JWT.

        Raises:
            RuntimeError: When using static credentials (bucket-specific not supported).
        """
        static, method = resolve_credentials(
            access_key_id=self._access_key_id,
            secret_access_key=self._secret_access_key,
            session_token=self._session_token,
        )
        if method == "static" and static is not None:
            raise RuntimeError(
                "get_credentials_for_bucket is only for SSO flow. With static credentials, use a single client."
            )
        return self._get_sso_credentials_for_bucket(bucket)

    def _static_to_credentials(self, static: StaticCredentials) -> Credentials:
        """Convert static credentials to Credentials."""
        return Credentials(
            access_key_id=static.access_key_id,
            secret_access_key=static.secret_access_key,
            session_token=static.session_token,
            expiry=None,
        )

    def _get_sso_credentials(self) -> Credentials:
        """Get SSO credentials (cached or fresh from broker)."""
        cache_key = self._bucket or "default"
        return self._get_sso_credentials_for_bucket(cache_key)

    def _get_sso_credentials_for_bucket(self, bucket_or_default: str) -> Credentials:
        """Get SSO credentials for a bucket (cached or fresh from broker)."""
        cache_key = bucket_or_default
        now = datetime.now(timezone.utc)
        cached = self._sso_cache.get(cache_key)
        if cached and cached.expiry and cached.expiry > now + timedelta(seconds=_REFRESH_BUFFER_SECONDS):
            return cached

        broker_url = self._config.r2.broker_url
        if not broker_url:
            raise RuntimeError("Broker URL not configured. Set R2_BROKER_URL in your environment.")

        bucket_param = None if cache_key == "default" else cache_key
        token = get_cloudflare_token(self._config, bucket=bucket_param)
        result = exchange_token_for_credentials(token, broker_url, bucket=bucket_param)
        creds = Credentials(
            access_key_id=result["access_key_id"],
            secret_access_key=result["secret_access_key"],
            session_token=result.get("session_token"),
            expiry=_parse_expiry(result.get("expiration")),
        )
        self._sso_cache[cache_key] = creds
        return creds

    def to_refreshable_credentials(self) -> RefreshableCredentials:
        """Wrap for boto3/botocore RefreshableCredentials (auto-refresh)."""
        creds = self.get_credentials()

        def refresh() -> dict[str, Any]:
            c = self.get_credentials()
            return {
                "access_key": c.access_key_id,
                "secret_key": c.secret_access_key,
                "token": c.session_token,
                "expiry_time": c.expiry,
            }

        return RefreshableCredentials(
            access_key=creds.access_key_id,
            secret_key=creds.secret_access_key,
            token=creds.session_token,
            expiry_time=creds.expiry,
            refresh_using=refresh,
            method="r2-sso",
        )


def _parse_expiry(value: str | None) -> datetime | None:
    """Parse ISO expiration string to datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
