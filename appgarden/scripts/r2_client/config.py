"""Configuration management for r2-client.

Environment variables only — no config file required for drop-in use.
Precedence: Constructor args > Environment variables > Defaults

Compatible with kamiwaza-extensions-template: KAMIWAZA_REGISTRY_* vars.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Config paths (optional — used for token cache when SSO is needed)
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "r2-client"
DEFAULT_TOKEN_PATH = DEFAULT_CONFIG_DIR / "token.json"

# Environment variable names
ENV_ACCESS_KEY_ID = "R2_ACCESS_KEY_ID"
ENV_SECRET_ACCESS_KEY = "R2_SECRET_ACCESS_KEY"  # noqa: S105
ENV_ENDPOINT_URL = "R2_ENDPOINT_URL"
ENV_BROKER_URL = "R2_BROKER_URL"
ENV_ACCOUNT_ID = "R2_ACCOUNT_ID"

# kamiwaza-extensions-template compatibility
ENV_KAMIWAZA_REGISTRY_ENDPOINT = "KAMIWAZA_REGISTRY_ENDPOINT"
ENV_KAMIWAZA_REGISTRY_ACCOUNT_ID = "KAMIWAZA_REGISTRY_ACCOUNT_ID"


@dataclass
class R2Config:
    """R2 connection configuration."""

    account_id: str | None = None
    endpoint_url: str | None = None
    broker_url: str | None = None


@dataclass
class AuthConfig:
    """Authentication configuration (minimal — Cloudflare handles auth)."""

    token_cache_path: str | Path = field(default_factory=lambda: str(DEFAULT_TOKEN_PATH))


@dataclass
class DefaultsConfig:
    """Default values for client creation."""

    region: str = "auto"
    credential_ttl_seconds: int = 900


@dataclass
class Config:
    """Full configuration for r2-client.

    Loaded from environment variables only. No config file required.
    """

    r2: R2Config = field(default_factory=R2Config)
    auth: AuthConfig = field(default_factory=AuthConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)

    @classmethod
    def load(cls) -> Config:
        """Load configuration from environment variables."""
        config = cls()
        config._apply_env()
        return config

    def _apply_env(self) -> None:
        """Apply environment variable configuration."""
        if account_id := os.environ.get(ENV_ACCOUNT_ID):
            self.r2.account_id = account_id

        endpoint = os.environ.get(ENV_ENDPOINT_URL) or os.environ.get(ENV_KAMIWAZA_REGISTRY_ENDPOINT)
        if endpoint:
            self.r2.endpoint_url = endpoint
        elif account_id := os.environ.get(ENV_KAMIWAZA_REGISTRY_ACCOUNT_ID):
            self.r2.endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
            self.r2.account_id = account_id

        if broker_url := os.environ.get(ENV_BROKER_URL):
            self.r2.broker_url = broker_url.rstrip("/")

    def get_endpoint_url(self, override: str | None = None) -> str | None:
        """Get R2 endpoint URL with optional override."""
        if override:
            return override
        if self.r2.endpoint_url:
            return self.r2.endpoint_url
        if self.r2.account_id:
            return f"https://{self.r2.account_id}.r2.cloudflarestorage.com"
        return None
