"""Per-thread persistent cache for web search and fetch tool results."""

from __future__ import annotations

import json
import logging
import os
import threading
from hashlib import sha256
from pathlib import Path

from langchain.tools import ToolRuntime
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState

logger = logging.getLogger(__name__)

_CACHE_FILENAME = "web_tool_cache.json"
_THREAD_DATA_DIR_NAMES = {"workspace", "uploads", "outputs"}
_cache_locks: dict[str, threading.Lock] = {}
_cache_locks_guard = threading.Lock()


def get_cached_web_result(
    runtime: ToolRuntime[ContextT, ThreadState] | None,
    *,
    provider: str,
    tool_name: str,
    value: str,
) -> str | None:
    """Return a cached web tool result for the current thread, if available."""
    cache_path = _resolve_cache_path(runtime)
    if cache_path is None:
        return None

    lock = _get_cache_lock(cache_path)
    cache_key = _make_cache_key(provider=provider, tool_name=tool_name, value=value)
    with lock:
        cache_data = _read_cache_file(cache_path)
        entry = cache_data.get(cache_key)
        if not isinstance(entry, dict):
            return None
        result = entry.get("result")
        if isinstance(result, str) and result:
            logger.info("Using cached %s result for %s", tool_name, provider)
            return result
    return None


def cache_web_result(
    runtime: ToolRuntime[ContextT, ThreadState] | None,
    *,
    provider: str,
    tool_name: str,
    value: str,
    result: str,
) -> bool:
    """Persist a successful web tool result for the current thread."""
    if not _is_cacheable_result(result):
        return False

    cache_path = _resolve_cache_path(runtime)
    if cache_path is None:
        return False

    lock = _get_cache_lock(cache_path)
    cache_key = _make_cache_key(provider=provider, tool_name=tool_name, value=value)
    with lock:
        cache_data = _read_cache_file(cache_path)
        cache_data[cache_key] = {
            "provider": provider,
            "tool_name": tool_name,
            "value": value,
            "result": result,
        }
        _write_cache_file(cache_path, cache_data)
    return True


def _resolve_cache_path(runtime: ToolRuntime[ContextT, ThreadState] | None) -> Path | None:
    if runtime is None:
        return None

    thread_data = runtime.state.get("thread_data") if runtime.state else None
    if not isinstance(thread_data, dict):
        return None

    user_data_dir = _get_user_data_dir(thread_data)
    if user_data_dir is None:
        return None

    cache_dir = user_data_dir / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / _CACHE_FILENAME


def _get_user_data_dir(thread_data: dict[str, str | None]) -> Path | None:
    for key in ("workspace_path", "uploads_path", "outputs_path"):
        value = thread_data.get(key)
        if not value:
            continue
        path = Path(value)
        if path.name in _THREAD_DATA_DIR_NAMES:
            return path.parent
        return path
    return None


def _make_cache_key(*, provider: str, tool_name: str, value: str) -> str:
    raw = "\0".join((provider, tool_name, value))
    return sha256(raw.encode("utf-8")).hexdigest()


def _get_cache_lock(cache_path: Path) -> threading.Lock:
    key = str(cache_path)
    with _cache_locks_guard:
        lock = _cache_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _cache_locks[key] = lock
        return lock


def _read_cache_file(cache_path: Path) -> dict[str, dict[str, str]]:
    if not cache_path.exists():
        return {}
    try:
        with cache_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read web cache file %s", cache_path, exc_info=True)
        return {}


def _write_cache_file(cache_path: Path, data: dict[str, dict[str, str]]) -> None:
    tmp_path = cache_path.with_name(f"{cache_path.name}.tmp")
    serialized = json.dumps(data, ensure_ascii=False, indent=2)
    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
    tmp_path.replace(cache_path)


def _is_cacheable_result(result: str) -> bool:
    stripped = result.strip()
    if not stripped or stripped.startswith("Error:"):
        return False

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return True

    if isinstance(parsed, dict) and "error" in parsed:
        return False
    return True
