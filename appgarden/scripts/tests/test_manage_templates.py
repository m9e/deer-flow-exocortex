"""Tests for manage-templates SDK fallback behavior."""

import builtins
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "manage-templates.py"
SPEC = importlib.util.spec_from_file_location("manage_templates", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load module from {MODULE_PATH}")
manage_templates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manage_templates)


def test_get_client_falls_back_to_requests(monkeypatch):
    session = manage_templates.requests.Session()
    monkeypatch.setattr(manage_templates, "_load_sdk", lambda: (None, None))
    monkeypatch.setattr(
        manage_templates,
        "_create_authenticated_session",
        lambda base_url, username, password, skip_auth=False: (session, False),
    )

    client = manage_templates.get_client("https://localhost/api", "admin", "kamiwaza")

    assert isinstance(client, manage_templates.RequestsKamiwazaClient)
    assert client.session is session


def test_list_app_templates_uses_explicit_template_type():
    calls: list[tuple[str, dict[str, str]]] = []

    class DummyClient:
        def get(self, path, params=None):
            calls.append((path, params))
            return [{"name": "skills-library", "version": "0.1.0"}]

    templates = manage_templates._list_app_templates(DummyClient(), "service")

    assert calls == [("/apps/app_templates", {"template_type": "service"})]
    assert templates[0].name == "skills-library"
    assert templates[0].model_dump()["version"] == "0.1.0"


def test_create_authenticated_session_uses_password_grant(monkeypatch):
    calls: list[SimpleNamespace] = []

    class DummyResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

    class DummySession:
        def __init__(self):
            self.headers = {}
            self.cookies = SimpleNamespace(values={}, set=lambda key, value: self.cookies.values.__setitem__(key, value))
            self.verify = True

        def post(self, url, data=None, headers=None, params=None):
            calls.append(SimpleNamespace(url=url, data=data, headers=headers, params=params))
            return DummyResponse(200, {"access_token": "token-123"})

    monkeypatch.setattr(manage_templates.requests, "Session", DummySession)

    session, authenticated = manage_templates._create_authenticated_session(
        "https://localhost/api",
        "admin",
        "kamiwaza",
    )

    assert authenticated is True
    assert session.headers["Authorization"] == "Bearer token-123"
    assert session.cookies.values["access_token"] == "token-123"
    assert calls[0].url == "https://localhost/api/auth/token"
    assert calls[0].data["grant_type"] == "password"
    assert calls[0].data["client_id"] == "kamiwaza-platform"


def test_create_authenticated_session_falls_back_to_local_login(monkeypatch):
    calls: list[SimpleNamespace] = []

    class DummyResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

    class DummySession:
        def __init__(self):
            self.headers = {}
            self.cookies = SimpleNamespace(values={}, set=lambda key, value: self.cookies.values.__setitem__(key, value))
            self.verify = True

        def post(self, url, data=None, headers=None, params=None):
            calls.append(SimpleNamespace(url=url, data=data, headers=headers, params=params))
            if url.endswith("/auth/token"):
                return DummyResponse(404)
            return DummyResponse(200, {"access_token": "dev-token"})

    monkeypatch.setattr(manage_templates.requests, "Session", DummySession)

    session, authenticated = manage_templates._create_authenticated_session(
        "https://localhost/api",
        "admin",
        "kamiwaza",
    )

    assert authenticated is True
    assert session.headers["Authorization"] == "Bearer dev-token"
    assert [call.url for call in calls] == [
        "https://localhost/api/auth/token",
        "https://localhost/api/auth/local-login",
    ]
    assert calls[1].data == {"username": "admin", "password": "kamiwaza"}
    assert calls[1].params is None


def test_to_records_handles_empty_payload():
    assert manage_templates._to_records(None) == []
    assert manage_templates._to_records([]) == []


def test_compat_response_raise_for_status_uses_server_error_for_5xx():
    response = manage_templates.CompatResponse(502, b"bad gateway", {}, "https://localhost/api/test")

    with pytest.raises(manage_templates.CompatHTTPError, match="502 Server Error"):
        response.raise_for_status()


def test_manage_templates_imports_without_requests_or_urllib3(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"requests", "urllib3"}:
            raise ImportError("No module named 'requests'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    spec = importlib.util.spec_from_file_location("manage_templates_no_requests", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._REQUESTS_AVAILABLE is False
    assert module.requests.Session is module.CompatSession


def test_garden_push_tool_template_uses_raw_template_listing(monkeypatch, tmp_path, capsys):
    repo_root = tmp_path
    tool_dir = repo_root / "tools" / "demo-tool"
    tool_dir.mkdir(parents=True)

    class DummyToolsService:
        def list_imported_templates(self):
            raise AssertionError("garden_push_tool_template should not use SDK tool schema listing here")

    class DummyClient:
        def __init__(self):
            self.tools = DummyToolsService()
            self.get_calls = []
            self.put_calls = []

        def get(self, path, params=None):
            self.get_calls.append((path, params))
            return [{"id": "template-123", "name": "demo-tool"}]

        def put(self, endpoint, json=None):
            self.put_calls.append((endpoint, json))
            return {"version": "1.2.3"}

        def post(self, endpoint, json=None):
            raise AssertionError("Existing tool template should be updated, not created")

    client = DummyClient()

    monkeypatch.setattr(manage_templates, "REPO_ROOT", repo_root)
    monkeypatch.setattr(manage_templates, "_load_metadata", lambda _: {"name": "demo-tool"})
    monkeypatch.setattr(
        manage_templates,
        "_load_registry_tool_entry",
        lambda tool_name, template_name: {
            "name": "demo-tool",
            "version": "1.2.3",
            "description": "Demo tool",
            "image": "kamiwazaai/demo-tool:1.2.3",
        },
    )
    monkeypatch.setattr(manage_templates, "_attach_preview_image_data", lambda payload, tool_path: None)
    monkeypatch.setattr(manage_templates, "get_client", lambda *args, **kwargs: client)

    manage_templates.garden_push_tool_template(
        "https://localhost/api",
        "admin",
        "kamiwaza",
        "demo-tool",
        skip_auth=True,
    )

    assert client.get_calls == [("/apps/app_templates", {"template_type": "tool"})]
    assert client.put_calls[0][0] == "/tool/tool_templates/template-123"
    assert "Successfully updated tool template 'demo-tool'" in capsys.readouterr().out


def test_requests_client_request_reraises_http_error_with_detail(monkeypatch):
    class DummyResponse:
        text = "forbidden"
        content = b"forbidden"

        def raise_for_status(self):
            raise manage_templates.requests.HTTPError("boom")

    class DummySession:
        def request(self, method, url, **kwargs):
            return DummyResponse()

    monkeypatch.setattr(
        manage_templates,
        "_create_authenticated_session",
        lambda base_url, username, password, skip_auth=False: (DummySession(), False),
    )

    client = manage_templates.RequestsKamiwazaClient("https://localhost/api")

    with pytest.raises(manage_templates.requests.HTTPError, match="boom - forbidden"):
        client.get("/apps/app_templates")


def test_garden_list_templates_warns_when_tool_listing_fails(monkeypatch, capsys):
    class DummyToolsService:
        def list_imported_templates(self):
            raise RuntimeError("tools unavailable")

    class DummyClient:
        def __init__(self):
            self.tools = DummyToolsService()

        def get(self, path, params=None):
            if params == {"template_type": "app"}:
                return [{"id": "app-1", "name": "demo-app", "version": "1.0.0"}]
            if params == {"template_type": "service"}:
                return [{"id": "svc-1", "name": "service-demo", "version": "1.0.0"}]
            raise AssertionError(f"Unexpected get call: {path} {params}")

    monkeypatch.setattr(manage_templates, "get_client", lambda *args, **kwargs: DummyClient())

    manage_templates.garden_list_templates("https://localhost/api", "admin", "kamiwaza")

    captured = capsys.readouterr()
    assert "Could not list tool templates: tools unavailable" in captured.err
    assert "demo-app" in captured.out
    assert "service-demo" in captured.out


def test_garden_list_templates_handles_missing_display_fields(monkeypatch, capsys):
    class DummyToolsService:
        def list_imported_templates(self):
            return []

    class DummyClient:
        def __init__(self):
            self.tools = DummyToolsService()

        def get(self, path, params=None):
            if params == {"template_type": "app"}:
                return [{"id": None, "name": None, "version": None}]
            if params == {"template_type": "service"}:
                return [{"id": None, "name": None, "version": None, "template_type": "service"}]
            raise AssertionError(f"Unexpected get call: {path} {params}")

    monkeypatch.setattr(manage_templates, "get_client", lambda *args, **kwargs: DummyClient())

    manage_templates.garden_list_templates("https://localhost/api", "admin", "kamiwaza")

    captured = capsys.readouterr()
    assert "unknown" in captured.out
    assert "n/a" in captured.out


def test_list_commands_handle_missing_names_and_stdout_stays_clean_for_json(monkeypatch, capsys):
    class DummyClient:
        def get(self, path, params=None):
            if params == {"template_type": "app"}:
                return [{"name": None, "version": "1.0.0", "risk_tier": 1, "verified": False, "description": None}]
            if params == {"template_type": "service"}:
                return [{"name": None, "version": "2.0.0", "risk_tier": 1, "verified": True, "description": None}]
            raise AssertionError(f"Unexpected get call: {path} {params}")

        class apps:
            @staticmethod
            def list_deployments():
                return [SimpleNamespace(name=None, status=None, id=None)]

        class tools:
            @staticmethod
            def list_deployments():
                return []

    manage_templates.list_app_templates(DummyClient(), output_format="table")
    manage_templates.list_service_templates(DummyClient(), output_format="table")
    manage_templates.list_deployments(DummyClient(), output_format="all")

    captured = capsys.readouterr()
    assert "unknown" in captured.out

    session = manage_templates.requests.Session()
    monkeypatch.setattr(manage_templates, "_load_sdk", lambda: (None, None))
    monkeypatch.setattr(
        manage_templates,
        "_create_authenticated_session",
        lambda base_url, username, password, skip_auth=False: (session, False),
    )

    manage_templates.get_client("https://localhost/api")

    captured = capsys.readouterr()
    assert "kamiwaza_sdk not installed" in captured.err
    assert captured.out == ""


def test_main_updates_tools_registry_file_for_repo_version(monkeypatch):
    original_registry_root = manage_templates.REGISTRY_ROOT
    original_apps_registry = manage_templates.APPS_REGISTRY_FILE
    original_tools_registry = manage_templates.TOOLS_REGISTRY_FILE
    original_detected_version = manage_templates._DETECTED_VERSION
    captured = {}

    def fake_garden_push_tool_template(*args, **kwargs):
        captured["tools_registry"] = manage_templates.TOOLS_REGISTRY_FILE

    monkeypatch.setattr(manage_templates, "garden_push_tool_template", fake_garden_push_tool_template)
    monkeypatch.setattr(
        manage_templates.sys,
        "argv",
        ["manage-templates.py", "--repo-version", "3", "garden-push", "tool", "demo-tool", "--no-auth"],
    )

    try:
        manage_templates.main()
    finally:
        manage_templates.REGISTRY_ROOT = original_registry_root
        manage_templates.APPS_REGISTRY_FILE = original_apps_registry
        manage_templates.TOOLS_REGISTRY_FILE = original_tools_registry
        manage_templates._DETECTED_VERSION = original_detected_version

    assert str(captured["tools_registry"]).endswith("/build/kamiwaza-extension-registry/garden/v3/tools.json")
