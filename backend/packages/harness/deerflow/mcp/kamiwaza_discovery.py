"""Discover Kamiwaza ToolShed MCP servers for DeerFlow."""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from deerflow.config.extensions_config import McpServerConfig

logger = logging.getLogger(__name__)

FALSEY = {"0", "false", "no", "off"}
TOOLSHED_HOSTNAME = "toolshed.default.deployment.kamiwaza.ai"


def discovery_enabled() -> bool:
    return os.getenv("KAMIWAZA_TOOL_DISCOVERY_ENABLED", "false").strip().lower() not in FALSEY


def _verify_ssl() -> bool:
    value = os.getenv("KAMIWAZA_VERIFY_SSL", os.getenv("MCP_VERIFY_SSL", "true"))
    return value.strip().lower() not in FALSEY


def _api_base() -> str:
    return os.getenv("KAMIWAZA_API_URL", "https://host.docker.internal/api").rstrip("/")


def _auth_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    token = (
        os.getenv("KAMIWAZA_PAT")
        or os.getenv("KAMIWAZA_API_KEY")
        or os.getenv("KAMIWAZA_API_TOKEN")
        or os.getenv("KAIZEN_PAT")
        or os.getenv("KAMIWAZA_ACCESS_TOKEN")
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _ensure_mcp_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path.endswith("/mcp"):
        path = f"{path}/mcp"
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment))


def _safe_server_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-").lower()
    return f"kamiwaza-{cleaned or 'tool'}"


def _prefer_internal_endpoint() -> bool:
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        return True
    return os.getenv("KAMIWAZA_TOOL_DISCOVERY_ENDPOINT_MODE", "auto").strip().lower() == "internal"


def _select_endpoint(endpoints: dict[str, Any], fallback_url: str | None = None) -> str | None:
    mode = os.getenv("KAMIWAZA_TOOL_DISCOVERY_ENDPOINT_MODE", "auto").strip().lower()
    internal_url = endpoints.get("internal")
    external_url = endpoints.get("external") or fallback_url

    if mode == "internal":
        return internal_url or external_url
    if mode == "external":
        return external_url or internal_url
    if _prefer_internal_endpoint():
        return internal_url or external_url
    return external_url or internal_url


def _tool_template_map(templates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for template in templates:
        name = template.get("name")
        if isinstance(name, str):
            result[name] = template
        template_id = template.get("id")
        if isinstance(template_id, str):
            result[template_id] = template
    return result


async def _get_json(client: httpx.AsyncClient, path: str) -> Any:
    response = await client.get(f"{_api_base()}{path}", headers=_auth_headers())
    response.raise_for_status()
    return response.json()


async def _discover_from_extensions(
    client: httpx.AsyncClient,
    templates_by_key: dict[str, dict[str, Any]],
) -> dict[str, McpServerConfig]:
    discovered: dict[str, McpServerConfig] = {}
    extensions = await _get_json(client, "/extensions")
    if not isinstance(extensions, list):
        return discovered

    for extension in extensions:
        if not isinstance(extension, dict):
            continue
        if extension.get("type") != "tool" or extension.get("phase") not in {"Running", "DEPLOYED", "Deployed"}:
            continue
        name = str(extension.get("name") or extension.get("id") or "tool")
        url = _select_endpoint(extension.get("endpoints") or {})
        if not url:
            continue
        template = templates_by_key.get(name, {})
        discovered[_safe_server_name(name)] = McpServerConfig(
            enabled=True,
            type="http",
            url=_ensure_mcp_path(url),
            headers=_auth_headers(),
            description=str(template.get("description") or f"Kamiwaza ToolShed MCP: {name}"),
        )
    return discovered


async def _discover_from_legacy_deployments(
    client: httpx.AsyncClient,
    templates_by_key: dict[str, dict[str, Any]],
) -> dict[str, McpServerConfig]:
    discovered: dict[str, McpServerConfig] = {}
    deployments = await _get_json(client, "/tool/deployments")
    if not isinstance(deployments, list):
        return discovered

    for deployment in deployments:
        if not isinstance(deployment, dict) or deployment.get("status") != "DEPLOYED":
            continue
        name = str(deployment.get("name") or deployment.get("id") or "tool")
        url = _select_endpoint({}, fallback_url=deployment.get("url"))
        if not url:
            continue
        template = templates_by_key.get(str(deployment.get("template_id") or ""), {})
        discovered[_safe_server_name(name)] = McpServerConfig(
            enabled=True,
            type="http",
            url=_ensure_mcp_path(url),
            headers=_auth_headers(),
            description=str(template.get("description") or f"Kamiwaza ToolShed MCP: {name}"),
        )
    return discovered


async def discover_kamiwaza_mcp_servers() -> dict[str, McpServerConfig]:
    """Return running Kamiwaza tool extensions as DeerFlow MCP server configs."""
    if not discovery_enabled():
        return {}

    timeout = float(os.getenv("KAMIWAZA_TOOL_DISCOVERY_TIMEOUT", "10"))
    async with httpx.AsyncClient(timeout=timeout, verify=_verify_ssl()) as client:
        templates_by_key: dict[str, dict[str, Any]] = {}
        try:
            templates = await _get_json(client, "/tool/templates")
            if isinstance(templates, list):
                templates_by_key = _tool_template_map(templates)
        except Exception as exc:
            logger.info("Kamiwaza tool template enrichment unavailable: %s", exc)

        try:
            discovered = await _discover_from_extensions(client, templates_by_key)
            if discovered:
                logger.info("Discovered %d Kamiwaza ToolShed MCP server(s)", len(discovered))
                return discovered
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {404, 501}:
                logger.warning("Kamiwaza /extensions discovery failed: %s", exc)
        except Exception as exc:
            logger.warning("Kamiwaza /extensions discovery failed: %s", exc)

        try:
            discovered = await _discover_from_legacy_deployments(client, templates_by_key)
            if discovered:
                logger.info("Discovered %d legacy Kamiwaza ToolShed MCP server(s)", len(discovered))
            return discovered
        except Exception as exc:
            logger.warning("Kamiwaza legacy ToolShed discovery failed: %s", exc)
            return {}
