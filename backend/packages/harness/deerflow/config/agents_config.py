"""Configuration and loaders for custom agents."""

import json
import logging
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml
from pydantic import BaseModel

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

SOUL_FILENAME = "SOUL.md"
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")
REMOTE_AGENTS_API_BASE_URL_ENV = "DEER_FLOW_AGENTS_API_BASE_URL"
REMOTE_AGENTS_API_TIMEOUT_SECONDS_ENV = "DEER_FLOW_AGENTS_API_TIMEOUT_SECONDS"


def remote_agents_store_configured() -> bool:
    """Return whether this process should use a remote custom-agent store."""
    return bool(_remote_agents_api_base_url())


def validate_agent_name(name: str | None) -> str | None:
    """Validate a custom agent name before using it in filesystem paths."""
    if name is None:
        return None
    if not isinstance(name, str):
        raise ValueError("Invalid agent name. Expected a string or None.")
    if not AGENT_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid agent name '{name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")
    return name


class AgentConfig(BaseModel):
    """Configuration for a custom agent."""

    name: str
    description: str = ""
    model: str | None = None
    tool_groups: list[str] | None = None
    # skills controls which skills are loaded into the agent's prompt:
    # - None (or omitted): load all enabled skills (default fallback behavior)
    # - [] (explicit empty list): disable all skills
    # - ["skill1", "skill2"]: load only the specified skills
    skills: list[str] | None = None


def _remote_agents_api_base_url() -> str | None:
    base_url = os.getenv(REMOTE_AGENTS_API_BASE_URL_ENV, "").strip().rstrip("/")
    if base_url:
        return base_url

    # App Garden currently gives each service its own PVC even when Compose uses
    # the same named volume. In the LangGraph runtime, use gateway as the
    # canonical custom-agent store when the platform deployment id is available.
    if not os.getenv("LANGGRAPH_JOBS_PER_WORKER"):
        return None
    if channel_gateway_url := os.getenv("DEER_FLOW_CHANNELS_GATEWAY_URL", "").strip().rstrip("/"):
        return channel_gateway_url
    if deployment_id := os.getenv("KAMIWAZA_DEPLOYMENT_ID", "").strip():
        return f"http://{deployment_id}-gateway:8001"
    return None


def _remote_agents_api_timeout_seconds() -> float:
    raw = os.getenv(REMOTE_AGENTS_API_TIMEOUT_SECONDS_ENV, "5.0").strip()
    try:
        timeout = float(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; using 5.0s",
            REMOTE_AGENTS_API_TIMEOUT_SECONDS_ENV,
            raw,
        )
        return 5.0
    return max(timeout, 0.1)


def _remote_agents_api_url(path: str) -> str | None:
    base_url = _remote_agents_api_base_url()
    if not base_url:
        return None
    api_prefix = "" if base_url.endswith("/api") else "/api"
    return f"{base_url}{api_prefix}{path}"


def _remote_json_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    url = _remote_agents_api_url(path)
    if not url:
        return None

    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=_remote_agents_api_timeout_seconds()) as response:
        response_body = response.read()
        if not response_body:
            return {}
        return json.loads(response_body.decode("utf-8"))


def _fetch_remote_agent_data(name: str) -> dict[str, Any] | None:
    """Fetch one custom agent from the configured management API, if enabled."""
    if not _remote_agents_api_base_url():
        return None

    try:
        data = _remote_json_request("GET", f"/agents/{quote(name, safe='')}")
    except HTTPError as e:
        if e.code == 404:
            raise FileNotFoundError(f"Remote agent not found: {name}") from e
        logger.warning("Failed to fetch remote agent %r: HTTP %s", name, e.code)
        return None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to fetch remote agent %r: %s", name, e)
        return None

    if not isinstance(data, dict):
        logger.warning("Ignoring invalid remote agent response for %r: expected object", name)
        return None
    return data


def _agent_config_from_data(name: str, data: dict[str, Any]) -> AgentConfig:
    if "name" not in data:
        data = {**data, "name": name}
    known_fields = set(AgentConfig.model_fields.keys())
    normalized = {k: v for k, v in data.items() if k in known_fields}
    return AgentConfig(**normalized)


def sync_agent_to_remote_store(agent_name: str, *, soul: str, description: str) -> bool:
    """Upsert a custom agent into the configured remote management API."""
    agent_name = validate_agent_name(agent_name) or ""
    if not agent_name or not _remote_agents_api_base_url():
        return False

    update_payload: dict[str, Any] = {"description": description, "soul": soul}
    create_payload: dict[str, Any] = {
        "name": agent_name,
        "description": description,
        "soul": soul,
    }

    try:
        _remote_json_request("PUT", f"/agents/{quote(agent_name, safe='')}", update_payload)
        return True
    except HTTPError as e:
        if e.code != 404:
            logger.warning("Failed to update remote agent %r: HTTP %s", agent_name, e.code)
            return False
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to update remote agent %r: %s", agent_name, e)
        return False

    try:
        _remote_json_request("POST", "/agents", create_payload)
        return True
    except HTTPError as e:
        logger.warning("Failed to create remote agent %r: HTTP %s", agent_name, e.code)
        return False
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to create remote agent %r: %s", agent_name, e)
        return False


def load_agent_config(name: str | None) -> AgentConfig | None:
    """Load the custom or default agent's config from its directory.

    Args:
        name: The agent name.

    Returns:
        AgentConfig instance.

    Raises:
        FileNotFoundError: If the agent directory or config.yaml does not exist.
        ValueError: If config.yaml cannot be parsed.
    """

    if name is None:
        return None

    name = validate_agent_name(name)
    remote_data = _fetch_remote_agent_data(name)
    if remote_data is not None:
        return _agent_config_from_data(name, remote_data)

    agent_dir = get_paths().agent_dir(name)
    config_file = agent_dir / "config.yaml"

    if not agent_dir.exists():
        raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

    if not config_file.exists():
        raise FileNotFoundError(f"Agent config not found: {config_file}")

    try:
        with open(config_file, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse agent config {config_file}: {e}") from e

    # Ensure name is set from directory name if not in file
    if "name" not in data:
        data["name"] = name

    # Strip unknown fields before passing to Pydantic (e.g. legacy prompt_file)
    known_fields = set(AgentConfig.model_fields.keys())
    data = {k: v for k, v in data.items() if k in known_fields}

    return AgentConfig(**data)


def load_agent_soul(agent_name: str | None) -> str | None:
    """Read the SOUL.md file for a custom agent, if it exists.

    SOUL.md defines the agent's personality, values, and behavioral guardrails.
    It is injected into the lead agent's system prompt as additional context.

    Args:
        agent_name: The name of the agent or None for the default agent.

    Returns:
        The SOUL.md content as a string, or None if the file does not exist.
    """
    if agent_name:
        agent_name = validate_agent_name(agent_name)
        try:
            remote_data = _fetch_remote_agent_data(agent_name)
        except FileNotFoundError:
            return None
        if remote_data is not None:
            soul = remote_data.get("soul")
            return soul.strip() if isinstance(soul, str) and soul.strip() else None

    agent_dir = get_paths().agent_dir(agent_name) if agent_name else get_paths().base_dir
    soul_path = agent_dir / SOUL_FILENAME
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    return content or None


def list_custom_agents() -> list[AgentConfig]:
    """Scan the agents directory and return all valid custom agents.

    Returns:
        List of AgentConfig for each valid agent directory found.
    """
    agents_dir = get_paths().agents_dir

    if not agents_dir.exists():
        return []

    agents: list[AgentConfig] = []

    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_dir():
            continue

        config_file = entry / "config.yaml"
        if not config_file.exists():
            logger.debug(f"Skipping {entry.name}: no config.yaml")
            continue

        try:
            agent_cfg = load_agent_config(entry.name)
            agents.append(agent_cfg)
        except Exception as e:
            logger.warning(f"Skipping agent '{entry.name}': {e}")

    return agents
