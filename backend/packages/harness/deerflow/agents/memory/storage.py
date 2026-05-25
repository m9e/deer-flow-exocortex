"""Memory storage providers."""

import abc
import json
import logging
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from deerflow.config.agents_config import AGENT_NAME_PATTERN
from deerflow.config.memory_config import get_memory_config
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

REMOTE_MEMORY_API_BASE_URL_ENV = "DEER_FLOW_MEMORY_API_BASE_URL"
REMOTE_MEMORY_API_TIMEOUT_SECONDS_ENV = "DEER_FLOW_MEMORY_API_TIMEOUT_SECONDS"


def utc_now_iso_z() -> str:
    """Current UTC time as ISO-8601 with ``Z`` suffix (matches prior naive-UTC output)."""
    return datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"


def create_empty_memory() -> dict[str, Any]:
    """Create an empty memory structure."""
    return {
        "version": "1.0",
        "lastUpdated": utc_now_iso_z(),
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }


class MemoryStorage(abc.ABC):
    """Abstract base class for memory storage providers."""

    @abc.abstractmethod
    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Load memory data for the given agent."""
        pass

    @abc.abstractmethod
    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Force reload memory data for the given agent."""
        pass

    @abc.abstractmethod
    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        """Save memory data for the given agent."""
        pass


class FileMemoryStorage(MemoryStorage):
    """File-based memory storage provider."""

    def __init__(self):
        """Initialize the file memory storage."""
        # Per-user/agent memory cache: keyed by (user_id, agent_name) tuple (None = global)
        # Value: (memory_data, file_mtime)
        self._memory_cache: dict[tuple[str | None, str | None], tuple[dict[str, Any], float | None]] = {}
        # Guards all reads and writes to _memory_cache across concurrent callers.
        self._cache_lock = threading.Lock()

    def _validate_agent_name(self, agent_name: str) -> None:
        """Validate that the agent name is safe to use in filesystem paths.

        Uses the repository's established AGENT_NAME_PATTERN to ensure consistency
        across the codebase and prevent path traversal or other problematic characters.
        """
        if not agent_name:
            raise ValueError("Agent name must be a non-empty string.")
        if not AGENT_NAME_PATTERN.match(agent_name):
            raise ValueError(f"Invalid agent name {agent_name!r}: names must match {AGENT_NAME_PATTERN.pattern}")

    def _get_memory_file_path(self, agent_name: str | None = None, *, user_id: str | None = None) -> Path:
        """Get the path to the memory file."""
        if user_id is not None:
            if agent_name is not None:
                self._validate_agent_name(agent_name)
                return get_paths().user_agent_memory_file(user_id, agent_name)
            config = get_memory_config()
            if config.storage_path and Path(config.storage_path).is_absolute():
                return Path(config.storage_path)
            return get_paths().user_memory_file(user_id)
        # Legacy: no user_id
        if agent_name is not None:
            self._validate_agent_name(agent_name)
            return get_paths().agent_memory_file(agent_name)
        config = get_memory_config()
        if config.storage_path:
            p = Path(config.storage_path)
            return p if p.is_absolute() else get_paths().base_dir / p
        return get_paths().memory_file

    def _load_memory_from_file(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Load memory data from file."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)

        if not file_path.exists():
            return create_empty_memory()

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load memory file: %s", e)
            return create_empty_memory()

    @staticmethod
    def _cache_key(agent_name: str | None = None, *, user_id: str | None = None) -> tuple[str | None, str | None]:
        return (user_id, agent_name)

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Load memory data (cached with file modification time check)."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        cache_key = self._cache_key(agent_name, user_id=user_id)

        try:
            current_mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            current_mtime = None

        with self._cache_lock:
            cached = self._memory_cache.get(cache_key)
            if cached is not None and cached[1] == current_mtime:
                return cached[0]

        memory_data = self._load_memory_from_file(agent_name, user_id=user_id)

        with self._cache_lock:
            self._memory_cache[cache_key] = (memory_data, current_mtime)

        return memory_data

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Reload memory data from file, forcing cache invalidation."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        memory_data = self._load_memory_from_file(agent_name, user_id=user_id)
        cache_key = self._cache_key(agent_name, user_id=user_id)

        try:
            mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            mtime = None

        with self._cache_lock:
            self._memory_cache[cache_key] = (memory_data, mtime)
        return memory_data

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        """Save memory data to file and update cache."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        cache_key = self._cache_key(agent_name, user_id=user_id)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            # Shallow-copy before adding lastUpdated so the caller's dict is not
            # mutated as a side-effect, and the cache reference is not silently
            # updated before the file write succeeds.
            memory_data = {**memory_data, "lastUpdated": utc_now_iso_z()}

            temp_path = file_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(memory_data, f, indent=2, ensure_ascii=False)

            temp_path.replace(file_path)

            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                mtime = None

            with self._cache_lock:
                self._memory_cache[cache_key] = (memory_data, mtime)
            logger.info("Memory saved to %s", file_path)
            return True
        except OSError as e:
            logger.error("Failed to save memory file: %s", e)
            return False


def _remote_memory_api_base_url() -> str | None:
    base_url = os.getenv(REMOTE_MEMORY_API_BASE_URL_ENV, "").strip().rstrip("/")
    if base_url:
        return base_url

    if not os.getenv("LANGGRAPH_JOBS_PER_WORKER"):
        return None
    if channel_gateway_url := os.getenv("DEER_FLOW_CHANNELS_GATEWAY_URL", "").strip().rstrip("/"):
        return channel_gateway_url
    if deployment_id := os.getenv("KAMIWAZA_DEPLOYMENT_ID", "").strip():
        return f"http://{deployment_id}-gateway:8001"
    return None


def _remote_memory_api_timeout_seconds() -> float:
    raw = os.getenv(REMOTE_MEMORY_API_TIMEOUT_SECONDS_ENV, "5.0").strip()
    try:
        timeout = float(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; using 5.0s",
            REMOTE_MEMORY_API_TIMEOUT_SECONDS_ENV,
            raw,
        )
        return 5.0
    return max(timeout, 0.1)


def _remote_memory_api_path(path: str, agent_name: str | None = None) -> str:
    if not agent_name:
        return path
    return f"{path}?{urlencode({'agent_name': agent_name})}"


def _remote_memory_api_url(path: str, agent_name: str | None = None) -> str | None:
    base_url = _remote_memory_api_base_url()
    if not base_url:
        return None
    api_prefix = "" if base_url.endswith("/api") else "/api"
    return f"{base_url}{api_prefix}{_remote_memory_api_path(path, agent_name)}"


class RemoteMemoryStorage(MemoryStorage):
    """Gateway-backed memory storage for split App Garden service volumes."""

    def __init__(self):
        self._base_url = _remote_memory_api_base_url()
        if not self._base_url:
            raise ValueError(f"{REMOTE_MEMORY_API_BASE_URL_ENV} is not configured")

    def _validate_agent_name(self, agent_name: str | None) -> None:
        if agent_name is None:
            return
        if not agent_name or not AGENT_NAME_PATTERN.match(agent_name):
            raise ValueError(f"Invalid agent name {agent_name!r}: names must match {AGENT_NAME_PATTERN.pattern}")

    def _json_request(
        self,
        method: str,
        path: str,
        agent_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_agent_name(agent_name)
        url = _remote_memory_api_url(path, agent_name)
        if not url:
            raise ValueError(f"{REMOTE_MEMORY_API_BASE_URL_ENV} is not configured")

        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=body, headers=headers, method=method)
        with urlopen(request, timeout=_remote_memory_api_timeout_seconds()) as response:
            response_body = response.read()
            if not response_body:
                return {}
            data = json.loads(response_body.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Remote memory API returned non-object JSON")
            return data

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        try:
            return self._json_request("GET", "/memory", agent_name)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as e:
            logger.warning("Failed to load remote memory for agent %r: %s", agent_name, e)
            return create_empty_memory()

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        try:
            return self._json_request("POST", "/memory/reload", agent_name)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as e:
            logger.warning("Failed to reload remote memory for agent %r: %s", agent_name, e)
            return create_empty_memory()

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        try:
            self._json_request("POST", "/memory/import", agent_name, memory_data)
            return True
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as e:
            logger.warning("Failed to save remote memory for agent %r: %s", agent_name, e)
            return False


_storage_instance: MemoryStorage | None = None
_storage_lock = threading.Lock()


def get_memory_storage() -> MemoryStorage:
    """Get the configured memory storage instance."""
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    with _storage_lock:
        if _storage_instance is not None:
            return _storage_instance

        if _remote_memory_api_base_url():
            _storage_instance = RemoteMemoryStorage()
            return _storage_instance

        config = get_memory_config()
        storage_class_path = config.storage_class

        try:
            module_path, class_name = storage_class_path.rsplit(".", 1)
            import importlib

            module = importlib.import_module(module_path)
            storage_class = getattr(module, class_name)

            # Validate that the configured storage is a MemoryStorage implementation
            if not isinstance(storage_class, type):
                raise TypeError(f"Configured memory storage '{storage_class_path}' is not a class: {storage_class!r}")
            if not issubclass(storage_class, MemoryStorage):
                raise TypeError(f"Configured memory storage '{storage_class_path}' is not a subclass of MemoryStorage")

            _storage_instance = storage_class()
        except Exception as e:
            logger.error(
                "Failed to load memory storage %s, falling back to FileMemoryStorage: %s",
                storage_class_path,
                e,
            )
            _storage_instance = FileMemoryStorage()

    return _storage_instance
