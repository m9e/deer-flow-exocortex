from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelListEndpointConfig(BaseModel):
    """Optional OpenAI-compatible model discovery endpoint."""

    enabled: bool = Field(default=True, description="Whether dynamic model discovery is enabled")
    url: str | None = Field(default=None, description="Endpoint that returns an OpenAI-style /v1/models payload")
    headers: dict[str, str] = Field(default_factory=dict, description="Optional headers for fetching the model list")
    timeout_sec: float = Field(default=10.0, description="Timeout for the model list fetch in seconds")
    cache_ttl_sec: int = Field(default=30, description="How long to cache fetched models before refreshing")
    use: str = Field(
        default="langchain_openai:ChatOpenAI",
        description="Class path of the provider used to instantiate discovered models",
    )
    base_url: str | None = Field(default=None, description="Base URL used to invoke discovered models")
    model_config = ConfigDict(extra="allow")

    def invocation_defaults(self) -> dict[str, Any]:
        """Return ModelConfig-compatible defaults for discovered models."""

        return self.model_dump(
            exclude_none=True,
            exclude={"enabled", "url", "headers", "timeout_sec", "cache_ttl_sec"},
        )

    def is_configured(self) -> bool:
        """Return True when the endpoint has enough configuration to be used."""

        return self.enabled and bool(self.url and self.base_url and self.use)
