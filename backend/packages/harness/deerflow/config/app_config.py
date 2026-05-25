import logging
import os
import re
import time
from collections.abc import Mapping
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlparse

import httpx
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from deerflow.config.acp_config import ACPAgentConfig, load_acp_config_from_dict
from deerflow.config.agents_api_config import AgentsApiConfig, load_agents_api_config_from_dict
from deerflow.config.checkpointer_config import CheckpointerConfig, load_checkpointer_config_from_dict
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.guardrails_config import GuardrailsConfig, load_guardrails_config_from_dict
from deerflow.config.kamiwaza_model_env import (
    apply_kamiwaza_env_defaults,
    infer_model_provider,
    normalize_kamiwaza_model_id,
)
from deerflow.config.loop_detection_config import LoopDetectionConfig
from deerflow.config.memory_config import MemoryConfig, load_memory_config_from_dict
from deerflow.config.model_config import ModelConfig
from deerflow.config.model_list_endpoint_config import ModelListEndpointConfig
from deerflow.config.run_events_config import RunEventsConfig
from deerflow.config.runtime_paths import existing_project_file
from deerflow.config.safety_finish_reason_config import SafetyFinishReasonConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.skill_evolution_config import SkillEvolutionConfig
from deerflow.config.skills_config import SkillsConfig
from deerflow.config.stream_bridge_config import StreamBridgeConfig, load_stream_bridge_config_from_dict
from deerflow.config.subagents_config import SubagentsAppConfig, load_subagents_config_from_dict
from deerflow.config.summarization_config import SummarizationConfig, load_summarization_config_from_dict
from deerflow.config.title_config import TitleConfig, load_title_config_from_dict
from deerflow.config.token_usage_config import TokenUsageConfig
from deerflow.config.tool_config import ToolConfig, ToolGroupConfig
from deerflow.config.tool_search_config import ToolSearchConfig, load_tool_search_config_from_dict

load_dotenv()

logger = logging.getLogger(__name__)


CONFIG_FILE_DATABASE_DEFAULTS = {
    "backend": "sqlite",
    "sqlite_dir": ".deer-flow/data",
}


class CircuitBreakerConfig(BaseModel):
    """Configuration for the LLM Circuit Breaker."""

    failure_threshold: int = Field(default=5, description="Number of consecutive failures before tripping the circuit")
    recovery_timeout_sec: int = Field(default=60, description="Time in seconds before attempting to recover the circuit")


def _legacy_config_candidates() -> tuple[Path, ...]:
    """Return source-tree config.yaml locations for monorepo compatibility."""
    backend_dir = Path(__file__).resolve().parents[4]
    repo_root = backend_dir.parent
    return (backend_dir / "config.yaml", repo_root / "config.yaml")


def _slugify_model_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "model"


def _titleize_slug(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", "-").split("-") if part)


def _display_name_for_discovered_model(model_name: str) -> str:
    parts = [part for part in model_name.split("/") if part]
    if len(parts) == 3 and parts[0].lower() == "kamiwaza":
        return f"{parts[2]} ({parts[1]})"
    if len(parts) == 2 and parts[0].lower() == "kamiwaza":
        return f"Kamiwaza {_titleize_slug(parts[1])}"
    return model_name


def _config_name_for_discovered_model(model_name: str) -> str:
    parts = [part for part in model_name.split("/") if part]
    if len(parts) == 3 and parts[0].lower() == "kamiwaza":
        return _slugify_model_name(parts[1])
    if len(parts) == 2 and parts[0].lower() == "kamiwaza":
        return _slugify_model_name(parts[1])
    return _slugify_model_name(model_name)


def _extract_model_ids_from_payload(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            payload = data
        else:
            payload = [payload]
    if not isinstance(payload, list):
        return []

    model_ids: list[str] = []
    seen: set[str] = set()
    for item in payload:
        model_id = None
        if isinstance(item, dict):
            candidate = item.get("id") or item.get("name")
            if candidate:
                model_id = str(candidate).strip()
        elif item:
            model_id = str(item).strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        model_ids.append(model_id)
    return model_ids


def _normalize_model_config_entry(model_dict: dict[str, Any]) -> dict[str, Any]:
    """Normalize a model config entry before validation."""
    normalized = dict(model_dict)
    provider = infer_model_provider(
        str(normalized.get("model", "")),
        base_url=str(normalized.get("base_url", "")),
        endpoint_path=str(normalized.get("endpoint_path", "")),
        provider=str(normalized.get("provider") or ""),
    )
    if provider is not None:
        normalized["provider"] = provider
    return apply_kamiwaza_env_defaults(normalized)


def _make_unique_model_name(candidate: str, used_names: set[str]) -> str:
    if candidate not in used_names:
        used_names.add(candidate)
        return candidate
    suffix = 2
    while True:
        next_name = f"{candidate}-{suffix}"
        if next_name not in used_names:
            used_names.add(next_name)
            return next_name
        suffix += 1


def _build_model_list_endpoint_model_configs(endpoint_config: ModelListEndpointConfig) -> list[ModelConfig]:
    if not endpoint_config.enabled:
        return []
    if not endpoint_config.is_configured():
        logger.warning("model_list_endpoint is missing required fields; expected url/use/base_url")
        return []

    try:
        with httpx.Client(timeout=httpx.Timeout(endpoint_config.timeout_sec), follow_redirects=True) as client:
            response = client.get(endpoint_config.url, headers=endpoint_config.headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("model_list_endpoint fetch failed for %s: %s", endpoint_config.url, exc)
        return []

    model_ids = _extract_model_ids_from_payload(payload)
    if not model_ids:
        return []

    used_names: set[str] = set()
    discovered: list[ModelConfig] = []
    for model_id in model_ids:
        canonical_model_id = normalize_kamiwaza_model_id(model_id)
        name = _make_unique_model_name(_config_name_for_discovered_model(canonical_model_id), used_names)
        defaults = endpoint_config.invocation_defaults()
        defaults.setdefault("display_name", _display_name_for_discovered_model(model_id))
        defaults.setdefault("description", f"Discovered from {endpoint_config.url}")
        discovered_entry = _normalize_model_config_entry(
            {
                **defaults,
                "name": name,
                "model": model_id,
            }
        )
        discovered.append(ModelConfig.model_validate(discovered_entry))
    return discovered


def _model_extra_value(model: ModelConfig, key: str) -> str:
    value = getattr(model, key, None)
    return str(value).strip() if value is not None else ""


def _url_matches_model_endpoint(left: str, right: str) -> bool:
    """Compare local model endpoint URLs while tolerating Docker host aliases."""

    left_url = urlparse(left)
    right_url = urlparse(right)
    if not left_url.scheme or not right_url.scheme:
        return left.rstrip("/") == right.rstrip("/")

    local_hosts = {"host.docker.internal", "localhost", "127.0.0.1"}
    left_host = left_url.hostname or ""
    right_host = right_url.hostname or ""
    hosts_match = left_host == right_host or (left_host in local_hosts and right_host in local_hosts)
    return (
        left_url.scheme == right_url.scheme
        and hosts_match
        and (left_url.port or _default_port(left_url.scheme)) == (right_url.port or _default_port(right_url.scheme))
        and left_url.path.rstrip("/") == right_url.path.rstrip("/")
    )


def _default_port(scheme: str) -> int | None:
    return {"http": 80, "https": 443}.get(scheme)


def _is_endpoint_managed_model(model: ModelConfig, endpoint_config: ModelListEndpointConfig | None) -> bool:
    if not endpoint_config:
        return False

    model_provider = (model.provider or "").lower()
    if model_provider == "kamiwaza":
        return True

    model_id = (model.model or "").strip().lower()
    if model_id.startswith("kamiwaza/"):
        return True

    endpoint_provider = str(getattr(endpoint_config, "provider", "") or "").lower()
    if endpoint_provider == "kamiwaza" and model_provider:
        return False

    if endpoint_provider == "kamiwaza" and model.use == endpoint_config.use and not _model_extra_value(model, "base_url"):
        return True

    endpoint_base_url = (endpoint_config.base_url or "").rstrip("/")
    model_base_url = _model_extra_value(model, "base_url").rstrip("/")
    if not endpoint_base_url or not model_base_url or model.use != endpoint_config.use:
        return False
    return _url_matches_model_endpoint(endpoint_base_url, model_base_url)


def _merge_model_configs(
    manual_models: list[ModelConfig],
    discovered_models: list[ModelConfig],
    endpoint_config: ModelListEndpointConfig | None = None,
) -> list[ModelConfig]:
    discovered_model_ids = {model.model for model in discovered_models}
    if discovered_models:
        merged = [
            model
            for model in manual_models
            if not _is_endpoint_managed_model(model, endpoint_config) or model.model in discovered_model_ids
        ]
    else:
        merged = list(manual_models)
    seen_model_ids = {model.model for model in merged}
    seen_names = {model.name for model in merged}

    for model in discovered_models:
        if model.model in seen_model_ids:
            continue
        if model.name in seen_names:
            model = model.model_copy(update={"name": _make_unique_model_name(model.name, seen_names)})
        else:
            seen_names.add(model.name)
        merged.append(model)
        seen_model_ids.add(model.model)
    return merged


def logging_level_from_config(name: str | None) -> int:
    """Map ``config.yaml`` ``log_level`` string to a :mod:`logging` level constant."""
    mapping = logging.getLevelNamesMapping()
    return mapping.get((name or "info").strip().upper(), logging.INFO)


def apply_logging_level(name: str | None) -> None:
    """Resolve *name* to a logging level and apply it to the ``deerflow``/``app`` logger hierarchies.

    Only the ``deerflow`` and ``app`` logger levels are changed so that
    third-party library verbosity (e.g. uvicorn, sqlalchemy) is not
    affected. Root handler levels are lowered (never raised) so that
    messages from the configured loggers can propagate through without
    being filtered, while preserving handler thresholds that may be
    intentionally restrictive for third-party log output.
    """
    level = logging_level_from_config(name)
    for logger_name in ("deerflow", "app"):
        logging.getLogger(logger_name).setLevel(level)
    for handler in logging.root.handlers:
        if level < handler.level:
            handler.setLevel(level)


class AppConfig(BaseModel):
    """Config for the DeerFlow application"""

    log_level: str = Field(default="info", description="Logging level for deerflow and app modules (debug/info/warning/error); third-party libraries are not affected")
    token_usage: TokenUsageConfig = Field(default_factory=TokenUsageConfig, description="Token usage tracking configuration")
    models: list[ModelConfig] = Field(default_factory=list, description="Available models")
    model_list_endpoint: ModelListEndpointConfig | None = Field(
        default=None,
        description="Optional OpenAI-compatible endpoint used to discover additional models",
    )
    sandbox: SandboxConfig = Field(description="Sandbox configuration")
    tools: list[ToolConfig] = Field(default_factory=list, description="Available tools")
    tool_groups: list[ToolGroupConfig] = Field(default_factory=list, description="Available tool groups")
    skills: SkillsConfig = Field(default_factory=SkillsConfig, description="Skills configuration")
    skill_evolution: SkillEvolutionConfig = Field(default_factory=SkillEvolutionConfig, description="Agent-managed skill evolution configuration")
    extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig, description="Extensions configuration (MCP servers and skills state)")
    tool_search: ToolSearchConfig = Field(default_factory=ToolSearchConfig, description="Tool search / deferred loading configuration")
    title: TitleConfig = Field(default_factory=TitleConfig, description="Automatic title generation configuration")
    summarization: SummarizationConfig = Field(default_factory=SummarizationConfig, description="Conversation summarization configuration")
    memory: MemoryConfig = Field(default_factory=MemoryConfig, description="Memory subsystem configuration")
    agents_api: AgentsApiConfig = Field(default_factory=AgentsApiConfig, description="Custom-agent management API configuration")
    acp_agents: dict[str, ACPAgentConfig] = Field(default_factory=dict, description="ACP-compatible agent configuration")
    subagents: SubagentsAppConfig = Field(default_factory=SubagentsAppConfig, description="Subagent runtime configuration")
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig, description="Guardrail middleware configuration")
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig, description="LLM circuit breaker configuration")
    loop_detection: LoopDetectionConfig = Field(default_factory=LoopDetectionConfig, description="Loop detection middleware configuration")
    safety_finish_reason: SafetyFinishReasonConfig = Field(default_factory=SafetyFinishReasonConfig, description="Provider safety-filter finish_reason interception middleware configuration")
    model_config = ConfigDict(extra="allow")
    database: DatabaseConfig = Field(default_factory=DatabaseConfig, description="Unified database backend configuration")
    run_events: RunEventsConfig = Field(default_factory=RunEventsConfig, description="Run event storage configuration")
    checkpointer: CheckpointerConfig | None = Field(default=None, description="Checkpointer configuration")
    stream_bridge: StreamBridgeConfig | None = Field(default=None, description="Stream bridge configuration")

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path:
        """Resolve the config file path.

        Priority:
        1. If provided `config_path` argument, use it.
        2. If provided `DEER_FLOW_CONFIG_PATH` environment variable, use it.
        3. Otherwise, search the caller project root.
        4. Finally, search legacy backend/repository-root defaults for monorepo compatibility.
        """
        if config_path:
            path = Path(config_path)
            if not Path.exists(path):
                raise FileNotFoundError(f"Config file specified by param `config_path` not found at {path}")
            return path
        elif os.getenv("DEER_FLOW_CONFIG_PATH"):
            path = Path(os.getenv("DEER_FLOW_CONFIG_PATH"))
            if not Path.exists(path):
                raise FileNotFoundError(f"Config file specified by environment variable `DEER_FLOW_CONFIG_PATH` not found at {path}")
            return path
        else:
            project_config = existing_project_file(("config.yaml",))
            if project_config is not None:
                return project_config

            for path in _legacy_config_candidates():
                if path.exists():
                    return path
            raise FileNotFoundError("`config.yaml` file not found in the project root or legacy backend/repository root locations")

    @classmethod
    def from_file(cls, config_path: str | None = None) -> Self:
        """Load config from YAML file.

        See `resolve_config_path` for more details.

        Args:
            config_path: Path to the config file.

        Returns:
            AppConfig: The loaded config.
        """
        resolved_path = cls.resolve_config_path(config_path)
        with open(resolved_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        # Check config version before processing
        cls._check_config_version(config_data, resolved_path)

        config_data = cls.resolve_env_variables(config_data)
        cls._apply_database_defaults(config_data)

        # Load circuit_breaker config if present
        if "circuit_breaker" in config_data:
            config_data["circuit_breaker"] = config_data["circuit_breaker"]

        # Load extensions config separately (it's in a different file)
        extensions_config = ExtensionsConfig.from_file()
        config_data["extensions"] = extensions_config.model_dump()
        models = config_data.get("models", [])
        if isinstance(models, list):
            config_data["models"] = [_normalize_model_config_entry(model) if isinstance(model, dict) else model for model in models]

        result = cls.model_validate(config_data)
        if result.model_list_endpoint is not None:
            discovered_models = _build_model_list_endpoint_model_configs(result.model_list_endpoint)
            result.models = _merge_model_configs(result.models, discovered_models, result.model_list_endpoint)
        acp_agents = cls._validate_acp_agents(config_data.get("acp_agents", {}))
        cls._apply_singleton_configs(result, acp_agents)
        return result

    @classmethod
    def _validate_acp_agents(
        cls,
        config_data: Mapping[str, Mapping[str, object]] | None,
    ) -> dict[str, ACPAgentConfig]:
        if config_data is None:
            config_data = {}
        return {name: ACPAgentConfig(**cfg) for name, cfg in config_data.items()}

    @classmethod
    def _apply_singleton_configs(cls, config: Self, acp_agents: dict[str, ACPAgentConfig]) -> None:
        from deerflow.config.checkpointer_config import get_checkpointer_config

        previous_checkpointer_config = get_checkpointer_config()

        load_title_config_from_dict(config.title.model_dump())
        load_summarization_config_from_dict(config.summarization.model_dump())
        load_memory_config_from_dict(config.memory.model_dump())
        load_agents_api_config_from_dict(config.agents_api.model_dump())
        load_subagents_config_from_dict(config.subagents.model_dump())
        load_tool_search_config_from_dict(config.tool_search.model_dump())
        load_guardrails_config_from_dict(config.guardrails.model_dump())
        load_checkpointer_config_from_dict(config.checkpointer.model_dump() if config.checkpointer is not None else None)
        load_stream_bridge_config_from_dict(config.stream_bridge.model_dump() if config.stream_bridge is not None else None)
        load_acp_config_from_dict({name: agent.model_dump() for name, agent in acp_agents.items()})

        if previous_checkpointer_config != config.checkpointer:
            # These runtime singletons derive their backend from checkpointer config.
            # Keep imports local to avoid cycles: both providers import get_app_config.
            from deerflow.runtime.checkpointer import reset_checkpointer
            from deerflow.runtime.store import reset_store

            reset_checkpointer()
            reset_store()

    @classmethod
    def _apply_database_defaults(cls, config_data: dict[str, Any]) -> None:
        """Apply config.yaml defaults for persistence when the section is absent."""
        database_config = config_data.get("database")
        if database_config is None:
            database_config = {}
            config_data["database"] = database_config
        if not isinstance(database_config, dict):
            return
        for key, value in CONFIG_FILE_DATABASE_DEFAULTS.items():
            database_config.setdefault(key, value)

    @classmethod
    def _check_config_version(cls, config_data: dict, config_path: Path) -> None:
        """Check if the user's config.yaml is outdated compared to config.example.yaml.

        Emits a warning if the user's config_version is lower than the example's.
        Missing config_version is treated as version 0 (pre-versioning).
        """
        try:
            user_version = int(config_data.get("config_version", 0))
        except (TypeError, ValueError):
            user_version = 0

        # Find config.example.yaml by searching config.yaml's directory and its parents
        example_path = None
        search_dir = config_path.parent
        for _ in range(5):  # search up to 5 levels
            candidate = search_dir / "config.example.yaml"
            if candidate.exists():
                example_path = candidate
                break
            parent = search_dir.parent
            if parent == search_dir:
                break
            search_dir = parent
        if example_path is None:
            return

        try:
            with open(example_path, encoding="utf-8") as f:
                example_data = yaml.safe_load(f)
            raw = example_data.get("config_version", 0) if example_data else 0
            try:
                example_version = int(raw)
            except (TypeError, ValueError):
                example_version = 0
        except Exception:
            return

        if user_version < example_version:
            logger.warning(
                "Your config.yaml (version %d) is outdated — the latest version is %d. Run `make config-upgrade` to merge new fields into your config.",
                user_version,
                example_version,
            )

    @classmethod
    def resolve_env_variables(cls, config: Any) -> Any:
        """Recursively resolve environment variables in the config.

        Environment variables are resolved using the `os.getenv` function. Example: $OPENAI_API_KEY

        Args:
            config: The config to resolve environment variables in.

        Returns:
            The config with environment variables resolved.
        """
        if isinstance(config, str):
            if config.startswith("$"):
                env_value = os.getenv(config[1:])
                if env_value is None:
                    raise ValueError(f"Environment variable {config[1:]} not found for config value {config}")
                return env_value
            return config
        elif isinstance(config, dict):
            return {k: cls.resolve_env_variables(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [cls.resolve_env_variables(item) for item in config]
        return config

    def get_model_config(self, name: str) -> ModelConfig | None:
        """Get the model config by name.

        Args:
            name: The name of the model to get the config for.

        Returns:
            The model config if found, otherwise None.
        """
        return next((model for model in self.models if model.name == name), None)

    def get_tool_config(self, name: str) -> ToolConfig | None:
        """Get the tool config by name.

        Args:
            name: The name of the tool to get the config for.

        Returns:
            The tool config if found, otherwise None.
        """
        return next((tool for tool in self.tools if tool.name == name), None)

    def get_tool_group_config(self, name: str) -> ToolGroupConfig | None:
        """Get the tool group config by name.

        Args:
            name: The name of the tool group to get the config for.

        Returns:
            The tool group config if found, otherwise None.
        """
        return next((group for group in self.tool_groups if group.name == name), None)


# Compatibility singleton layer for code paths that have not yet been
# migrated to explicit ``AppConfig`` threading. New composition roots should
# prefer constructing ``AppConfig`` once and passing it down directly.
_app_config: AppConfig | None = None
_app_config_path: Path | None = None
_app_config_mtime: float | None = None
_app_config_dynamic_refresh_deadline: float | None = None
_app_config_is_custom = False
_current_app_config: ContextVar[AppConfig | None] = ContextVar("deerflow_current_app_config", default=None)
_current_app_config_stack: ContextVar[tuple[AppConfig | None, ...]] = ContextVar("deerflow_current_app_config_stack", default=())


def _get_config_mtime(config_path: Path) -> float | None:
    """Get the modification time of a config file if it exists."""
    try:
        return config_path.stat().st_mtime
    except OSError:
        return None


def _load_and_cache_app_config(config_path: str | None = None) -> AppConfig:
    """Load config from disk and refresh cache metadata."""
    global _app_config, _app_config_path, _app_config_mtime, _app_config_dynamic_refresh_deadline, _app_config_is_custom

    resolved_path = AppConfig.resolve_config_path(config_path)
    _app_config = AppConfig.from_file(str(resolved_path))
    _app_config_path = resolved_path
    _app_config_mtime = _get_config_mtime(resolved_path)
    endpoint_config = _app_config.model_list_endpoint
    if endpoint_config and endpoint_config.is_configured():
        _app_config_dynamic_refresh_deadline = time.monotonic() + endpoint_config.cache_ttl_sec
    else:
        _app_config_dynamic_refresh_deadline = None
    _app_config_is_custom = False
    return _app_config


def get_app_config() -> AppConfig:
    """Get the DeerFlow config instance.

    Returns a cached singleton instance and automatically reloads it when the
    underlying config file path or modification time changes. Use
    `reload_app_config()` to force a reload, or `reset_app_config()` to clear
    the cache.
    """
    global _app_config, _app_config_path, _app_config_mtime, _app_config_dynamic_refresh_deadline

    runtime_override = _current_app_config.get()
    if runtime_override is not None:
        return runtime_override

    if _app_config is not None and _app_config_is_custom:
        return _app_config

    resolved_path = AppConfig.resolve_config_path()
    current_mtime = _get_config_mtime(resolved_path)
    dynamic_refresh_due = _app_config_dynamic_refresh_deadline is not None and time.monotonic() >= _app_config_dynamic_refresh_deadline

    should_reload = _app_config is None or _app_config_path != resolved_path or _app_config_mtime != current_mtime or dynamic_refresh_due
    if should_reload:
        if _app_config_path == resolved_path and _app_config_mtime is not None and current_mtime is not None and _app_config_mtime != current_mtime:
            logger.info(
                "Config file has been modified (mtime: %s -> %s), reloading AppConfig",
                _app_config_mtime,
                current_mtime,
            )
        elif dynamic_refresh_due:
            logger.info("model_list_endpoint cache expired; reloading AppConfig")
        _load_and_cache_app_config(str(resolved_path))
    return _app_config


def reload_app_config(config_path: str | None = None) -> AppConfig:
    """Reload the config from file and update the cached instance.

    This is useful when the config file has been modified and you want
    to pick up the changes without restarting the application.

    Args:
        config_path: Optional path to config file. If not provided,
                     uses the default resolution strategy.

    Returns:
        The newly loaded AppConfig instance.
    """
    return _load_and_cache_app_config(config_path)


def reset_app_config() -> None:
    """Reset the cached config instance.

    This clears the singleton cache, causing the next call to
    `get_app_config()` to reload from file. Useful for testing
    or when switching between different configurations.
    """
    global _app_config, _app_config_path, _app_config_mtime, _app_config_dynamic_refresh_deadline, _app_config_is_custom
    _app_config = None
    _app_config_path = None
    _app_config_mtime = None
    _app_config_dynamic_refresh_deadline = None
    _app_config_is_custom = False


def set_app_config(config: AppConfig) -> None:
    """Set a custom config instance.

    This allows injecting a custom or mock config for testing purposes.

    Args:
        config: The AppConfig instance to use.
    """
    global _app_config, _app_config_path, _app_config_mtime, _app_config_dynamic_refresh_deadline, _app_config_is_custom
    _app_config = config
    _app_config_path = None
    _app_config_mtime = None
    _app_config_dynamic_refresh_deadline = None
    _app_config_is_custom = True


def peek_current_app_config() -> AppConfig | None:
    """Return the runtime-scoped AppConfig override, if one is active."""
    return _current_app_config.get()


def push_current_app_config(config: AppConfig) -> None:
    """Push a runtime-scoped AppConfig override for the current execution context."""
    stack = _current_app_config_stack.get()
    _current_app_config_stack.set(stack + (_current_app_config.get(),))
    _current_app_config.set(config)


def pop_current_app_config() -> None:
    """Pop the latest runtime-scoped AppConfig override for the current execution context."""
    stack = _current_app_config_stack.get()
    if not stack:
        _current_app_config.set(None)
        return
    previous = stack[-1]
    _current_app_config_stack.set(stack[:-1])
    _current_app_config.set(previous)
