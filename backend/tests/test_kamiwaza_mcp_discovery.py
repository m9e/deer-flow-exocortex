import httpx
import pytest

from deerflow.mcp.kamiwaza_discovery import discover_kamiwaza_mcp_servers


@pytest.mark.anyio
async def test_discover_kamiwaza_mcp_servers_from_extensions(monkeypatch):
    monkeypatch.setenv("KAMIWAZA_TOOL_DISCOVERY_ENABLED", "true")
    monkeypatch.setenv("KAMIWAZA_API_URL", "https://kamiwaza.test/api")
    monkeypatch.setenv("KAMIWAZA_VERIFY_SSL", "false")
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tool/templates":
            return httpx.Response(200, json=[{"name": "tool-demo", "description": "Demo tool"}])
        if request.url.path == "/api/extensions":
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "tool-demo",
                        "type": "tool",
                        "phase": "Running",
                        "endpoints": {
                            "internal": "http://tool-demo.kamiwaza-extensions.svc:8000",
                            "external": "https://toolshed.default.deployment.kamiwaza.ai/runtime/tools/demo",
                        },
                    }
                ],
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)

    servers = await discover_kamiwaza_mcp_servers()

    assert set(servers) == {"kamiwaza-tool-demo"}
    assert servers["kamiwaza-tool-demo"].url == (
        "https://toolshed.default.deployment.kamiwaza.ai/runtime/tools/demo/mcp"
    )
    assert servers["kamiwaza-tool-demo"].description == "Demo tool"


@pytest.mark.anyio
async def test_discover_kamiwaza_mcp_servers_disabled(monkeypatch):
    monkeypatch.setenv("KAMIWAZA_TOOL_DISCOVERY_ENABLED", "false")

    assert await discover_kamiwaza_mcp_servers() == {}
