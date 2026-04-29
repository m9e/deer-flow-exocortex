"""Canonical serialization for LangChain / LangGraph objects.

Provides a single source of truth for converting LangChain message
objects, Pydantic models, and LangGraph state dicts into plain
JSON-serialisable Python structures.

Consumers: ``deerflow.runtime.runs.worker`` (SSE publishing) and
``app.gateway.routers.threads`` (REST responses).
"""

from __future__ import annotations

import re
from typing import Any

_SYSTEM_REMINDER_BLOCK_RE = re.compile(r"<system_reminder\b[^>]*>[\s\S]*?</system_reminder>", re.IGNORECASE)
_SYSTEM_REMINDER_OPEN_RE = re.compile(r"<system_reminder\b[^>]*>[\s\S]*$", re.IGNORECASE)


def strip_internal_system_reminders(text: str) -> str:
    """Remove internal system-reminder blocks from text sent to clients."""
    cleaned = _SYSTEM_REMINDER_BLOCK_RE.sub("", text)
    # Streaming or failed generations can leave a partial block. Drop the
    # unterminated tail rather than rendering internal instructions.
    cleaned = _SYSTEM_REMINDER_OPEN_RE.sub("", cleaned)
    return cleaned.strip()


def _sanitize_content(value: Any) -> Any:
    if isinstance(value, str):
        return strip_internal_system_reminders(value)
    if isinstance(value, list):
        sanitized: list[Any] = []
        for item in value:
            if isinstance(item, str):
                sanitized.append(strip_internal_system_reminders(item))
            elif isinstance(item, dict):
                sanitized.append(_sanitize_message_dict(item))
            else:
                sanitized.append(serialize_lc_object(item))
        return sanitized
    return value


def _sanitize_message_dict(value: dict[str, Any]) -> dict[str, Any]:
    """Sanitize serialized message-like dictionaries."""
    result = dict(value)
    if "content" in result:
        result["content"] = _sanitize_content(result["content"])
    if "text" in result and isinstance(result["text"], str):
        result["text"] = strip_internal_system_reminders(result["text"])
    return result


def serialize_lc_object(obj: Any) -> Any:
    """Recursively serialize a LangChain object to a JSON-serialisable dict."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return _sanitize_message_dict({k: serialize_lc_object(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return [serialize_lc_object(item) for item in obj]
    # Pydantic v2
    if hasattr(obj, "model_dump"):
        try:
            value = obj.model_dump()
            if isinstance(value, dict):
                return _sanitize_message_dict(serialize_lc_object(value))
            return serialize_lc_object(value)
        except Exception:
            pass
    # Pydantic v1 / older objects
    if hasattr(obj, "dict"):
        try:
            value = obj.dict()
            if isinstance(value, dict):
                return _sanitize_message_dict(serialize_lc_object(value))
            return serialize_lc_object(value)
        except Exception:
            pass
    # Last resort
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def serialize_channel_values(channel_values: dict[str, Any]) -> dict[str, Any]:
    """Serialize channel values, stripping internal LangGraph keys.

    Internal keys like ``__pregel_*`` and ``__interrupt__`` are removed
    to match what the LangGraph Platform API returns.
    """
    result: dict[str, Any] = {}
    for key, value in channel_values.items():
        if key.startswith("__pregel_") or key == "__interrupt__":
            continue
        result[key] = serialize_lc_object(value)
    return result


def serialize_messages_tuple(obj: Any) -> Any:
    """Serialize a messages-mode tuple ``(chunk, metadata)``."""
    if isinstance(obj, tuple) and len(obj) == 2:
        chunk, metadata = obj
        return [serialize_lc_object(chunk), metadata if isinstance(metadata, dict) else {}]
    return serialize_lc_object(obj)


def serialize(obj: Any, *, mode: str = "") -> Any:
    """Serialize LangChain objects with mode-specific handling.

    * ``messages`` — obj is ``(message_chunk, metadata_dict)``
    * ``values`` — obj is the full state dict; ``__pregel_*`` keys stripped
    * everything else — recursive ``model_dump()`` / ``dict()`` fallback
    """
    if mode == "messages":
        return serialize_messages_tuple(obj)
    if mode == "values":
        return serialize_channel_values(obj) if isinstance(obj, dict) else serialize_lc_object(obj)
    return serialize_lc_object(obj)
