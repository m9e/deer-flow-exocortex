"""Helpers for resolving Kamiwaza model configuration from environment."""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

_APP_GARDEN_TEMPLATE_TOKEN_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


def _is_unresolved_template(value: str | None) -> bool:
    """Return True when a value still contains App Garden template placeholders."""
    if value is None:
        return True
    stripped = value.strip()
    if not stripped:
        return True
    return _APP_GARDEN_TEMPLATE_TOKEN_RE.search(stripped) is not None


def _read_env_value(*keys: str) -> str | None:
    """Return the first non-empty, non-template environment value for the keys."""
    for key in keys:
        raw = os.getenv(key)
        if raw is None:
            continue
        value = raw.strip()
        if not value or _is_unresolved_template(value):
            continue
        return value
    return None


def normalize_kamiwaza_model_id(model_id: str | None) -> str:
    """Return a trimmed Kamiwaza model ID without changing routing semantics.

    Deployment-qualified IDs such as ``kamiwaza/<alias>/<ModelName>`` are
    valid Kamiwaza model IDs and must remain intact. Stale deployment entries
    are filtered against the live model endpoint instead of being rewritten to
    ambiguous raw model names.
    """
    if model_id is None:
        return ""

    return model_id.strip()


def resolve_kamiwaza_model_name_from_env() -> str | None:
    """Resolve model name from known Kamiwaza/system env vars."""
    return _read_env_value("KAMIWAZA_MODEL_NAME", "MODEL_NAME", "OPENAI_MODEL", "LLM_MODEL")


def _normalize_runtime_model_path(raw_path: str) -> str | None:
    """Normalize path/URL to a runtime model endpoint path ending in /v1."""
    value = raw_path.strip()
    if not value:
        return None

    if "://" in value:
        value = urlparse(value).path or ""
    elif value.startswith(":"):
        slash_idx = value.find("/")
        value = value[slash_idx:] if slash_idx != -1 else ""

    if not value:
        return None
    if not value.startswith("/"):
        value = f"/{value}"

    if "/runtime/models/" not in value:
        return None

    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]

    value = value.rstrip("/")
    if not value.endswith("/v1"):
        value = f"{value}/v1"
    return value


def resolve_kamiwaza_endpoint_path_from_env() -> str | None:
    """Resolve runtime endpoint path for selected model from env vars."""
    for key in (
        "KAMIWAZA_MODEL_PATH",
        "KAMIWAZA_MODEL_PATH_URL",
        "KAMIWAZA_MODEL_URL",
        "OPENAI_BASE_URL",
    ):
        raw = _read_env_value(key)
        if not raw:
            continue
        normalized = _normalize_runtime_model_path(raw)
        if normalized:
            return normalized
    return None


def resolve_openai_base_url_from_env() -> str | None:
    """Resolve explicit OpenAI base URL from App Garden/injected env."""
    raw = _read_env_value("OPENAI_BASE_URL")
    return raw.rstrip("/") if raw else None


def infer_model_provider(model: str | None, *, base_url: str | None = None, endpoint_path: str | None = None, provider: str | None = None) -> str | None:
    """Infer provider when it is unset in model config.

    We intentionally keep inference conservative to avoid changing behavior for
    non-Kamiwaza models that happen to share a local gateway.
    """
    if provider and not _is_unresolved_template(provider):
        return provider

    candidate = (model or "").strip().lower()
    if not candidate:
        return None
    if candidate.startswith("kamiwaza/"):
        return "kamiwaza"

    check = (endpoint_path or "").strip().lower()
    if "/runtime/models/" in check:
        return "kamiwaza"

    base = (base_url or "").strip().lower()
    if "/runtime/models/" in base:
        return "kamiwaza"
    return None


def apply_kamiwaza_env_defaults(llm_config: dict[str, object]) -> dict[str, object]:
    """Apply env-driven defaults for Kamiwaza model configs.

    This is a safe fallback when model-selection fields are placeholders or empty
    and App Garden has already injected selected-model env vars.
    """
    if not isinstance(llm_config, dict):
        return llm_config

    provider = str(llm_config.get("provider") or "").strip().lower()
    if _is_unresolved_template(provider):
        provider = ""
    if provider != "kamiwaza":
        return llm_config

    resolved: dict[str, object] = dict(llm_config)

    model_value = str(resolved.get("model") or "").strip()
    if not model_value or model_value in {"default", "openai/default"}:
        env_model = resolve_kamiwaza_model_name_from_env()
        if env_model:
            resolved["model"] = env_model
    resolved["model"] = normalize_kamiwaza_model_id(str(resolved.get("model") or ""))

    endpoint_path = str(resolved.get("endpoint_path") or "").strip()
    if not endpoint_path or _is_unresolved_template(endpoint_path):
        env_endpoint_path = resolve_kamiwaza_endpoint_path_from_env()
        if env_endpoint_path:
            resolved["endpoint_path"] = env_endpoint_path

    base_url = str(resolved.get("base_url") or "").strip()
    if not base_url or _is_unresolved_template(base_url):
        env_base_url = resolve_openai_base_url_from_env()
        if env_base_url:
            resolved["base_url"] = env_base_url

    return resolved
