#!/usr/bin/env python3
"""Manage Kamiwaza templates - list, import, sync, and push templates."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from dataclasses import dataclass
from http import HTTPStatus
from http.cookiejar import CookieJar
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.error import HTTPError as UrllibHTTPError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor
from urllib.request import HTTPSHandler
from urllib.request import Request
from urllib.request import build_opener

try:
    import urllib3 as _urllib3
except ImportError:
    _urllib3 = None

try:
    import requests as _requests
except ImportError:
    _requests = None

if _urllib3 is not None:
    _urllib3.disable_warnings(_urllib3.exceptions.InsecureRequestWarning)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = REPO_ROOT / "build"
_FALSEY = {"0", "false", "no", "off"}
_REQUESTS_AVAILABLE = _requests is not None
_SDK_CLIENT_CLASS: Any = None
_SDK_AUTH_CLASS: Any = None
_SDK_LOAD_ATTEMPTED = False
_SDK_AVAILABLE = False


class CompatHTTPError(Exception):
    """Minimal replacement for requests.HTTPError when requests is unavailable."""

    def __init__(self, message: str, response: Any = None, request: Any = None):
        super().__init__(message)
        self.response = response
        self.request = request


class CompatRequestException(Exception):
    """Minimal replacement for requests.RequestException when requests is unavailable."""


class CompatCookies(dict):
    """Tiny cookie jar API used by tests and auth helpers."""

    def set(self, key: str, value: str) -> None:
        self[key] = value


class CompatResponse:
    """Response shim with the subset of requests.Response used in this script."""

    def __init__(self, status_code: int, body: bytes, headers: Any, url: str, request: Any = None):
        self.status_code = status_code
        self._body = body
        self.headers = headers
        self.url = url
        self.request = request

    @property
    def content(self) -> bytes:
        return self._body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code < 400:
            return
        try:
            phrase = HTTPStatus(self.status_code).phrase
        except ValueError:
            phrase = "HTTP Error"
        error_type = "Server Error" if self.status_code >= 500 else "Client Error"
        raise CompatHTTPError(
            f"{self.status_code} {error_type}: {phrase} for url: {self.url}",
            response=self,
            request=self.request,
        )


def _create_unverified_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class CompatSession:
    """Small urllib-backed session used when requests is unavailable."""

    def __init__(self):
        self.headers: dict[str, str] = {}
        self.cookies = CompatCookies()
        self.verify = True
        self._cookie_jar = CookieJar()

    def _build_opener(self):
        handlers = [HTTPCookieProcessor(self._cookie_jar)]
        if not self.verify:
            context = _create_unverified_ssl_context()
            handlers.append(HTTPSHandler(context=context))
        return build_opener(*handlers)

    def request(self, method: str, url: str, **kwargs: Any) -> CompatResponse:
        params = kwargs.pop("params", None)
        data = kwargs.pop("data", None)
        json_payload = kwargs.pop("json", None)
        request_headers = dict(self.headers)
        request_headers.update(kwargs.pop("headers", {}) or {})
        timeout = kwargs.pop("timeout", 30)
        if kwargs:
            raise TypeError(f"Unsupported request kwargs: {sorted(kwargs)}")

        if params:
            encoded = urlencode(params)
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{encoded}"

        body = None
        if json_payload is not None:
            body = json.dumps(json_payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif data is not None:
            if isinstance(data, dict):
                body = urlencode(data).encode("utf-8")
            elif isinstance(data, str):
                body = data.encode("utf-8")
            else:
                body = data

        request = Request(url, data=body, headers=request_headers, method=method.upper())
        opener = self._build_opener()
        try:
            with opener.open(request, timeout=timeout) as response:
                return CompatResponse(
                    response.status,
                    response.read(),
                    response.headers,
                    response.geturl(),
                    request=request,
                )
        except UrllibHTTPError as exc:
            return CompatResponse(exc.code, exc.read(), exc.headers, exc.geturl(), request=request)
        except URLError as exc:
            raise CompatRequestException(str(exc)) from exc

    def get(self, url: str, **kwargs: Any) -> CompatResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> CompatResponse:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> CompatResponse:
        return self.request("PUT", url, **kwargs)


if _requests is None:
    class _RequestsCompatModule:
        Session = CompatSession
        HTTPError = CompatHTTPError
        RequestException = CompatRequestException

    requests = _RequestsCompatModule()
else:
    requests = _requests


def _verify_ssl() -> bool:
    return os.getenv("KAMIWAZA_VERIFY_SSL", "true").strip().lower() not in _FALSEY


def _load_sdk() -> tuple[Any | None, Any | None]:
    global _SDK_AUTH_CLASS, _SDK_AVAILABLE, _SDK_CLIENT_CLASS, _SDK_LOAD_ATTEMPTED
    if _SDK_LOAD_ATTEMPTED:
        return _SDK_CLIENT_CLASS, _SDK_AUTH_CLASS

    _SDK_LOAD_ATTEMPTED = True
    for package_name in ("kamiwaza_sdk", "kamiwaza_client"):
        try:
            package = import_module(package_name)
            auth_module = import_module(f"{package_name}.authentication")
            _SDK_CLIENT_CLASS = getattr(package, "KamiwazaClient")
            _SDK_AUTH_CLASS = getattr(auth_module, "UserPasswordAuthenticator")
            _SDK_AVAILABLE = True
            return _SDK_CLIENT_CLASS, _SDK_AUTH_CLASS
        except ImportError:
            continue

    _SDK_AVAILABLE = False
    return None, None


class CompatRecord(dict):
    """Dict wrapper that behaves enough like SDK models for this script."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def dict(self) -> dict[str, Any]:
        return dict(self)

    def model_dump(self) -> dict[str, Any]:
        return dict(self)


def _to_records(payload: list[dict[str, Any]] | None) -> list[CompatRecord]:
    if not payload:
        return []
    return [CompatRecord(item) for item in payload]


@dataclass
class RequestsAppService:
    client: "RequestsKamiwazaClient"

    def list_templates(self, template_type: str = "app") -> list[CompatRecord]:
        response = self.client.get("/apps/app_templates", params={"template_type": template_type})
        return _to_records(response)

    def list_deployments(self) -> list[CompatRecord]:
        response = self.client.get("/apps/deployments")
        return _to_records(response)


@dataclass
class RequestsToolService:
    client: "RequestsKamiwazaClient"

    def list_available_templates(self) -> list[CompatRecord]:
        response = self.client.get("/tool/templates/available")
        return _to_records(response)

    def list_imported_templates(self) -> list[CompatRecord]:
        response = self.client.get("/tool/templates")
        return _to_records(response)

    def list_deployments(self) -> list[CompatRecord]:
        response = self.client.get("/tool/deployments")
        return _to_records(response)


class RequestsKamiwazaClient:
    """Small requests-based fallback when the Python SDK is unavailable."""

    def __init__(self, base_url: str, username: str | None = None, password: str | None = None):
        self.base_url = _normalize_base_url(base_url)
        self.session, _ = _create_authenticated_session(
            base_url,
            username,
            password,
            skip_auth=not (username and password),
        )
        self.session.verify = _verify_ssl()
        self.apps = RequestsAppService(self)
        self.tools = RequestsToolService(self)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path if path.startswith('/') else f'/{path}'}"
        response = self.session.request(method, url, **kwargs)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text.strip()
            if detail:
                enriched = requests.HTTPError(f"{exc} - {detail}")
                setattr(enriched, "response", response)
                setattr(enriched, "request", getattr(exc, "request", None))
                raise enriched from exc
            raise
        if not response.content:
            return None
        return response.json()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, json=json)

    def put(self, path: str, json: dict[str, Any] | None = None) -> Any:
        return self._request("PUT", path, json=json)


def _list_app_templates(client: Any, template_type: str) -> list[CompatRecord]:
    response = client.get("/apps/app_templates", params={"template_type": template_type})
    return _to_records(response)


def _get_garden_dir_name(repo_version: str) -> str:
    """Map REPO_VERSION to directory name: 1 → 'default', everything else → 'v{N}'."""
    return "default" if repo_version == "1" else f"v{repo_version}"


def _get_registry_root(repo_version: str | None = None) -> tuple[Path, str]:
    """Get the registry root path for the specified repo version.

    If repo_version is None, auto-detect by reading .repo-version file,
    then checking the build directory for existing registry files.
    Returns tuple of (path, detected_repo_version).
    """
    base = BUILD_DIR / "kamiwaza-extension-registry" / "garden"
    file_version: str | None = None

    if repo_version:
        dir_name = _get_garden_dir_name(repo_version)
        return base / dir_name, repo_version

    # Auto-detect: read .repo-version file first (matches Makefile behavior)
    repo_version_file = REPO_ROOT / ".repo-version"
    if repo_version_file.exists():
        file_version = repo_version_file.read_text().strip()
        if file_version:
            dir_name = _get_garden_dir_name(file_version)
            versioned_path = base / dir_name
            if (versioned_path / "apps.json").exists():
                return versioned_path, file_version

    # Fallback: check v2, then default (legacy)
    v2_path = base / "v2"
    if (v2_path / "apps.json").exists():
        return v2_path, "2"

    default_path = base / "default"
    if (default_path / "apps.json").exists():
        return default_path, "1"

    # Final fallback: use .repo-version if present, else v2
    if file_version:
        dir_name = _get_garden_dir_name(file_version)
        return base / dir_name, file_version

    return v2_path, "2"


def _get_apps_registry_file(repo_version: str | None = None) -> Path:
    """Get the apps.json file path for the specified repo version."""
    registry_root, _ = _get_registry_root(repo_version)
    return registry_root / "apps.json"


# Default paths (auto-detected)
REGISTRY_ROOT, _DETECTED_VERSION = _get_registry_root()
APPS_REGISTRY_FILE = REGISTRY_ROOT / "apps.json"
LEGACY_APPS_REGISTRY_FILE = BUILD_DIR / "kamiwaza-extension-registry" / "garden" / "default" / "apps.json"


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _normalize_template_type_value(value: Any) -> str | None:
    if value is None:
        return None
    raw_value = getattr(value, "value", value)
    if isinstance(raw_value, str):
        cleaned = raw_value.strip().lower()
        if cleaned in {"apps", "tools", "services"}:
            cleaned = cleaned[:-1]
        if cleaned in {"app", "tool", "service"}:
            return cleaned
    return None


def _display_text(value: Any, default: str = "unknown") -> str:
    if value is None:
        return default
    text = str(value)
    return text if text else default


def _truncate_text(value: Any, limit: int, default: str = "unknown") -> str:
    text = _display_text(value, default=default)
    return text[: limit - 1] + "…" if len(text) > limit else text


def _resolve_template_type(name: str | None, template_type: Any) -> str:
    resolved = _normalize_template_type_value(template_type)
    if resolved:
        return resolved
    if isinstance(name, str):
        lowered = name.lower()
        if lowered.startswith(("tool-", "mcp-")):
            return "tool"
        if lowered.startswith("service-"):
            return "service"
    return "app"


def _get_template_field(template: Any, field: str, default: Any = None) -> Any:
    if hasattr(template, field):
        return getattr(template, field)
    if isinstance(template, dict):
        return template.get(field, default)
    return default


def _filter_templates(templates: list[Any], desired_type: str) -> list[Any]:
    filtered = []
    for tpl in templates:
        name = _get_template_field(tpl, "name")
        template_type = _get_template_field(tpl, "template_type")
        if _resolve_template_type(name, template_type) == desired_type:
            filtered.append(tpl)
    return filtered


def _load_metadata(app_path: Path) -> dict[str, Any]:
    metadata_path = app_path / "kamiwaza.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"No kamiwaza.json found at {metadata_path}")

    with metadata_path.open() as f:
        return json.load(f)


def _load_registry_app_entry(app_name: str, template_name: str | None) -> dict[str, Any]:
    paths_to_check = [APPS_REGISTRY_FILE, LEGACY_APPS_REGISTRY_FILE]
    last_path = None
    found_any_path = False

    for registry_path in paths_to_check:
        if not registry_path.exists():
            continue

        found_any_path = True
        last_path = registry_path

        with registry_path.open() as f:
            apps_registry = json.load(f)

        candidates = []
        for entry in apps_registry:
            entry_name = entry.get("name")
            if entry_name == template_name or entry_name == app_name:
                candidates.append(entry)

        if not candidates:
            continue

        if len(candidates) > 1:
            print(f"Warning: Multiple registry entries matched '{template_name or app_name}'. Using first match.")

        if registry_path == LEGACY_APPS_REGISTRY_FILE:
            print(
                "Warning: Using legacy registry path. Run 'make build-registry' to "
                "generate the v2 registry at build/kamiwaza-extension-registry/garden/v2/."
            )

        return candidates[0]

    if not found_any_path:
        raise FileNotFoundError("Registry apps.json not found. Run 'make build-registry' before pushing.")

    raise ValueError(f"Template '{template_name or app_name}' not found in {last_path}. Run 'make build-registry'.")


def _get_tools_registry_file(repo_version: str | None = None) -> Path:
    """Get the tools.json file path for the specified repo version."""
    registry_root, _ = _get_registry_root(repo_version)
    return registry_root / "tools.json"


# Default tools paths (auto-detected)
TOOLS_REGISTRY_FILE = REGISTRY_ROOT / "tools.json"
LEGACY_TOOLS_REGISTRY_FILE = BUILD_DIR / "kamiwaza-extension-registry" / "garden" / "default" / "tools.json"


def _load_registry_tool_entry(tool_name: str, template_name: str | None) -> dict[str, Any]:
    """Load a tool entry from the registry (tools.json)."""
    paths_to_check = [TOOLS_REGISTRY_FILE, LEGACY_TOOLS_REGISTRY_FILE]
    last_path = None
    found_any_path = False

    for registry_path in paths_to_check:
        if not registry_path.exists():
            continue

        found_any_path = True
        last_path = registry_path

        with registry_path.open() as f:
            tools_registry = json.load(f)

        candidates = []
        for entry in tools_registry:
            entry_name = entry.get("name")
            if entry_name == template_name or entry_name == tool_name:
                candidates.append(entry)

        if not candidates:
            continue

        if len(candidates) > 1:
            print(f"Warning: Multiple registry entries matched '{template_name or tool_name}'. Using first match.")

        if registry_path == LEGACY_TOOLS_REGISTRY_FILE:
            print(
                "Warning: Using legacy registry path. Run 'make build-registry' to "
                "generate the v2 registry at build/kamiwaza-extension-registry/garden/v2/."
            )

        return candidates[0]

    if not found_any_path:
        raise FileNotFoundError("Registry tools.json not found. Run 'make build-registry' before pushing.")

    raise ValueError(
        f"Tool template '{template_name or tool_name}' not found in {last_path}. Run 'make build-registry'."
    )


def _attach_preview_image_data(payload: dict[str, Any], extension_path: Path) -> None:
    """If payload has a convention preview_image, base64-encode the file and attach it."""
    import base64

    preview_image = payload.get("preview_image")
    if not preview_image or not isinstance(preview_image, str):
        return
    if not preview_image.startswith("images/"):
        return
    image_path = extension_path / preview_image
    if image_path.exists():
        payload["preview_image_data"] = base64.b64encode(image_path.read_bytes()).decode("ascii")
        print(f"  📷 Including preview image: {preview_image}")
    else:
        print(f"  ⚠️  Preview image not found: {image_path}")


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


def _set_access_token(session: requests.Session, access_token: str) -> None:
    session.headers.update({"Authorization": f"Bearer {access_token}"})
    session.cookies.set("access_token", access_token)


def _password_grant_login(
    session: requests.Session,
    base_url: str,
    username: str,
    password: str,
) -> bool | None:
    token_url = f"{_normalize_base_url(base_url)}/auth/token"
    response = session.post(
        token_url,
        data={
            "grant_type": "password",
            "username": username,
            "password": password,
            "scope": "openid email profile",
            "client_id": "kamiwaza-platform",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        print(f"⚠️  Password grant login failed ({response.status_code})")
        return False
    try:
        payload = response.json()
    except ValueError:
        print("⚠️  Password grant login did not return JSON")
        return False
    access_token = payload.get("access_token")
    if not access_token:
        print("⚠️  Password grant login did not return an access token")
        return False
    _set_access_token(session, access_token)
    return True


def _local_login(
    session: requests.Session,
    base_url: str,
    username: str,
    password: str,
) -> bool | None:
    login_url = f"{_normalize_base_url(base_url)}/auth/local-login"
    response = session.post(
        login_url,
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        print(f"⚠️  Local login failed ({response.status_code})")
        return False
    try:
        payload = response.json()
    except ValueError:
        return True
    access_token = payload.get("access_token")
    if access_token:
        _set_access_token(session, access_token)
    return True


def _create_authenticated_session(
    base_url: str, username: str | None, password: str | None, skip_auth: bool = False
) -> tuple[requests.Session, bool]:
    """Create a session, optionally with authentication.

    Returns:
        tuple of (session, is_authenticated)
    """
    session = requests.Session()
    session.verify = _verify_ssl()

    if skip_auth or not username or not password:
        return session, False

    try:
        password_grant = _password_grant_login(session, base_url, username, password)
        if password_grant:
            return session, True

        local_login = _local_login(session, base_url, username, password)
        if local_login:
            return session, True

        if password_grant is None and local_login is None:
            print("ℹ️  Auth endpoints not found - proceeding without authentication")
        else:
            print("   Attempting to proceed without authentication...")
        unauthenticated = requests.Session()
        unauthenticated.verify = _verify_ssl()
        return unauthenticated, False
    except requests.RequestException as exc:
        print(f"⚠️  Auth request failed: {exc}")
        print("   Attempting to proceed without authentication...")
        unauthenticated = requests.Session()
        unauthenticated.verify = _verify_ssl()
        return unauthenticated, False


def _find_app_template(session: requests.Session, base_url: str, name: str) -> dict[str, Any] | None:
    """Find an existing app template by name.

    Returns:
        Template dict if found, None if not found.
        Raises RuntimeError on auth failure.
    """
    templates_url = f"{_normalize_base_url(base_url)}/apps/app_templates"
    response = session.get(templates_url)

    if response.status_code == 401:
        raise RuntimeError("Authentication required to access templates API")
    elif response.status_code == 403:
        raise RuntimeError("Permission denied to access templates API")

    response.raise_for_status()
    for template in response.json():
        if template.get("name") == name:
            return template
    return None


def garden_push_app_template(
    base_url: str,
    username: str | None,
    password: str | None,
    app_name: str,
    override_template_id: str | None = None,
    skip_auth: bool = False,
    extension_dir: str = "apps",
    default_template_type: str | None = None,
) -> None:
    extension_path = REPO_ROOT / extension_dir / app_name
    extension_label = extension_dir.rstrip("s").capitalize()

    if not extension_path.exists():
        print(f"❌ Error: {extension_label} '{app_name}' not found at {extension_path}")
        sys.exit(1)

    try:
        metadata = _load_metadata(extension_path)
    except Exception as exc:
        print(f"❌ Error loading metadata: {exc}")
        sys.exit(1)

    template_name = metadata.get("name") or app_name

    try:
        registry_entry = _load_registry_app_entry(app_name, template_name)
    except Exception as exc:
        print(f"❌ {exc}")
        sys.exit(1)

    # Get compose content directly from registry entry
    compose_content = registry_entry.get("compose_yml")
    if not compose_content or not compose_content.strip():
        print(f"❌ Registry entry for '{template_name}' is missing compose_yml. Run 'make build-registry'.")
        sys.exit(1)

    payload = dict(registry_entry)
    payload.pop("id", None)
    for transient_key in ("owner_id", "created_at", "updated_at"):
        payload.pop(transient_key, None)
    payload["compose_yml"] = compose_content
    # Restore raw preview_image from kamiwaza.json (registry normalizes for CDN)
    raw_preview = metadata.get("preview_image")
    if raw_preview:
        payload["preview_image"] = raw_preview
    payload = _clean_payload(payload)
    _attach_preview_image_data(payload, extension_path)
    if default_template_type and not payload.get("template_type"):
        payload["template_type"] = default_template_type

    # Use SDK client for proper Keycloak authentication
    try:
        if skip_auth:
            client = get_client(base_url)
            is_authenticated = False
        else:
            client = get_client(base_url, username, password)
            is_authenticated = bool(username and password)
    except Exception as exc:
        print(f"❌ Failed to connect to Kamiwaza: {exc}")
        sys.exit(1)

    # Use SDK's HTTP client which has proper auth headers
    # Note: client.apps.list_templates() defaults to template_type=app on the
    # server side, so services and tools are excluded. Use the raw client.get
    # with an explicit template_type parameter to find existing templates of
    # the correct type.
    try:
        list_type = default_template_type or "app"
        raw_templates = client.get("/apps/app_templates", params={"template_type": list_type})
        templates = _to_records(raw_templates)
        existing = None
        if override_template_id:
            print(f"Using provided template_id {override_template_id} for update")
            existing = next((t for t in templates if str(t.id) == override_template_id), None)
            if not existing:
                existing = type("obj", (object,), {"id": override_template_id})()
        else:
            existing = next((t for t in templates if t.name == template_name), None)
    except Exception as exc:
        error_msg = str(exc)
        if "401" in error_msg or "Unauthorized" in error_msg:
            print("❌ Authentication required to access templates API")
            if skip_auth:
                print("   The target system requires authentication.")
                print("   Remove --no-auth and set KAMIWAZA_USERNAME/KAMIWAZA_PASSWORD.")
            else:
                print("   Verify KAMIWAZA_USERNAME and KAMIWAZA_PASSWORD are correct.")
            sys.exit(1)
        print(f"❌ Failed to list templates: {exc}")
        sys.exit(1)

    try:
        if existing:
            action = "update"
            template_id = existing.id if hasattr(existing, "id") else existing.get("id")
            endpoint = f"/apps/app_templates/{template_id}"
            result = client.put(endpoint, json=payload)
        else:
            action = "create"
            endpoint = "/apps/app_templates"
            result = client.post(endpoint, json=payload)

        # SDK returns parsed JSON directly, raises on error
        version = (
            result.get("version", payload.get("version", "unknown"))
            if isinstance(result, dict)
            else payload.get("version", "unknown")
        )
        auth_status = " (authenticated)" if is_authenticated else " (no auth)"
        past_tense = "updated" if action == "update" else "created"
        print(f"✅ Successfully {past_tense} template '{template_name}' (version {version}){auth_status}")
    except Exception as exc:
        error_msg = str(exc)
        if "401" in error_msg or "Unauthorized" in error_msg:
            print(f"❌ Authentication required to {action} template.")
            print("   Set KAMIWAZA_USERNAME and KAMIWAZA_PASSWORD environment variables.")
        else:
            print(f"❌ Failed to {action} template '{template_name}': {exc}")
        sys.exit(1)


def garden_push_tool_template(
    base_url: str,
    username: str | None,
    password: str | None,
    tool_name: str,
    override_template_id: str | None = None,
    skip_auth: bool = False,
) -> None:
    """Push a tool template to a Kamiwaza instance."""
    tool_path = REPO_ROOT / "tools" / tool_name

    if not tool_path.exists():
        print(f"❌ Error: Tool '{tool_name}' not found at {tool_path}")
        sys.exit(1)

    try:
        metadata = _load_metadata(tool_path)
    except Exception as exc:
        print(f"❌ Error loading metadata: {exc}")
        sys.exit(1)

    template_name = metadata.get("name") or tool_name

    try:
        registry_entry = _load_registry_tool_entry(tool_name, template_name)
    except Exception as exc:
        print(f"❌ {exc}")
        sys.exit(1)

    # Build payload from registry entry
    payload = dict(registry_entry)
    payload.pop("id", None)
    for transient_key in ("owner_id", "created_at", "updated_at", "template_id"):
        payload.pop(transient_key, None)

    # Ensure required fields have defaults
    if "capabilities" not in payload:
        payload["capabilities"] = []
    if "required_env_vars" not in payload:
        payload["required_env_vars"] = []
    if "env_defaults" not in payload:
        payload["env_defaults"] = {}
    if "tags" not in payload:
        payload["tags"] = []
    if "verified" not in payload:
        payload["verified"] = False
    if "risk_tier" not in payload:
        payload["risk_tier"] = 1

    # Restore raw preview_image from kamiwaza.json (registry normalizes for CDN)
    raw_preview = metadata.get("preview_image")
    if raw_preview:
        payload["preview_image"] = raw_preview
    payload = _clean_payload(payload)
    _attach_preview_image_data(payload, tool_path)

    # Use SDK client for proper authentication
    try:
        if skip_auth:
            client = get_client(base_url)
            is_authenticated = False
        else:
            client = get_client(base_url, username, password)
            is_authenticated = bool(username and password)
    except Exception as exc:
        print(f"❌ Failed to connect to Kamiwaza: {exc}")
        sys.exit(1)

    # Check if template already exists.
    # Use raw API payloads to avoid SDK schema validation failures on legacy/null fields.
    try:
        templates = client.get("/apps/app_templates", params={"template_type": "tool"}) or []
        existing = None
        if override_template_id:
            print(f"Using provided template_id {override_template_id} for update")
            existing = next((t for t in templates if str(t.get("id")) == override_template_id), None)
            if not existing:
                existing = {"id": override_template_id}
        else:
            existing = next((t for t in templates if t.get("name") == template_name), None)
    except Exception as exc:
        error_msg = str(exc)
        if "401" in error_msg or "Unauthorized" in error_msg:
            print("❌ Authentication required to access templates API")
            if skip_auth:
                print("   The target system requires authentication.")
                print("   Remove --no-auth and set KAMIWAZA_USERNAME/KAMIWAZA_PASSWORD.")
            else:
                print("   Verify KAMIWAZA_USERNAME and KAMIWAZA_PASSWORD are correct.")
            sys.exit(1)
        print(f"❌ Failed to list templates: {exc}")
        sys.exit(1)

    # Create or update tool template
    # Note: Tool templates use the same AppTemplate model as apps.
    # CREATE uses apps/app_templates (no separate tool create endpoint exists).
    # UPDATE uses tool/tool_templates/{id} for tool-specific operations.
    try:
        if existing:
            action = "update"
            template_id = existing.get("id")
            endpoint = f"/tool/tool_templates/{template_id}"
            result = client.put(endpoint, json=payload)
        else:
            action = "create"
            endpoint = "/apps/app_templates"
            result = client.post(endpoint, json=payload)

        version = (
            result.get("version", payload.get("version", "unknown"))
            if isinstance(result, dict)
            else payload.get("version", "unknown")
        )
        auth_status = " (authenticated)" if is_authenticated else " (no auth)"
        past_tense = "updated" if action == "update" else "created"
        print(f"✅ Successfully {past_tense} tool template '{template_name}' (version {version}){auth_status}")
    except Exception as exc:
        error_msg = str(exc)
        if "401" in error_msg or "Unauthorized" in error_msg:
            print(f"❌ Authentication required to {action} template.")
            print("   Set KAMIWAZA_USERNAME and KAMIWAZA_PASSWORD environment variables.")
        else:
            print(f"❌ Failed to {action} tool template '{template_name}': {exc}")
        sys.exit(1)


def garden_sync_templates(
    base_url: str,
    username: str | None,
    password: str | None,
    names: list[str] | None = None,
    remote_base_url: str | None = None,
    remote_apps_path: str | None = None,
    remote_tools_path: str | None = None,
    skip_auth: bool = False,
) -> None:
    print("⚠️  garden-sync is not implemented yet.")


def garden_list_templates(
    base_url: str,
    username: str | None,
    password: str | None,
    output_format: str = "table",
    skip_auth: bool = False,
) -> None:
    # Use SDK client for proper authentication
    try:
        if skip_auth:
            client = get_client(base_url)
        else:
            client = get_client(base_url, username, password)
    except Exception as exc:
        print(f"❌ Failed to connect to Kamiwaza: {exc}")
        sys.exit(1)

    try:
        templates = _list_app_templates(client, "app")
        templates.extend(_list_app_templates(client, "service"))
        try:
            templates.extend(client.tools.list_imported_templates())
        except Exception as exc:
            print(f"⚠️  Warning: Could not list tool templates: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"❌ Failed to list templates: {exc}")
        sys.exit(1)

    if output_format == "json":
        print(json.dumps([t.model_dump() for t in templates], indent=2, default=str))
        return

    if not templates:
        print("No templates found.")
        return

    print("\n📋 Installed Templates:")
    print(f"{'Name':<40} {'Type':<10} {'Version':<12} ID")
    print("-" * 100)
    for tpl in templates:
        raw_name = tpl.name if hasattr(tpl, "name") else tpl.get("name")
        raw_version = tpl.version if hasattr(tpl, "version") else tpl.get("version")
        raw_id = tpl.id if hasattr(tpl, "id") else tpl.get("id")
        name = _truncate_text(raw_name, 40)
        version = _display_text(raw_version, default="n/a")
        tpl_id = _display_text(raw_id, default="n/a")
        template_type = _resolve_template_type(name, getattr(tpl, "template_type", None))
        print(f"{name:<40} {template_type:<10} {version:<12} {tpl_id}")


def get_client(base_url: str, username: str | None = None, password: str | None = None) -> Any:
    """Initialize Kamiwaza client with optional authentication.

    Note: Set KAMIWAZA_VERIFY_SSL=false to disable SSL verification for self-signed certs.
    """
    sdk_client_class, sdk_auth_class = _load_sdk()
    if sdk_client_class and sdk_auth_class:
        client = sdk_client_class(base_url=base_url)
        if username and password:
            authenticator = sdk_auth_class(username=username, password=password, auth_service=client.auth)
            client = sdk_client_class(base_url=base_url, authenticator=authenticator)
        return client

    fallback_name = "requests" if _REQUESTS_AVAILABLE else "stdlib"
    print(f"ℹ️  kamiwaza_sdk not installed; using {fallback_name} fallback for template management", file=sys.stderr)
    return RequestsKamiwazaClient(base_url=base_url, username=username, password=password)


def list_app_templates(client: Any, output_format: str = "table") -> None:
    """List available app templates."""
    try:
        templates = _list_app_templates(client, "app")

        if output_format == "json":
            print(json.dumps([t.model_dump() for t in templates], indent=2, default=str))
        else:
            print(f"\n📋 Available App Templates ({len(templates)} total):\n")
            print(f"{'Name':<30} {'Version':<10} {'Risk':<6} {'Verified':<10} Description")
            print("-" * 90)
            for t in templates:
                name = _truncate_text(t.name, 30)
                desc = _truncate_text(t.description, 41, default="") if t.description else ""
                print(f"{name:<30} {t.version or '1.0.0':<10} {t.risk_tier:<6} {'✓' if t.verified else '✗':<10} {desc}")
    except Exception as e:
        print(f"❌ Error listing app templates: {e}", file=sys.stderr)
        sys.exit(1)


def list_service_templates(client: Any, output_format: str = "table") -> None:
    """List available service templates."""
    try:
        templates = _list_app_templates(client, "service")

        if output_format == "json":
            print(json.dumps([t.model_dump() for t in templates], indent=2, default=str))
        else:
            print(f"\n🧰 Available Service Templates ({len(templates)} total):\n")
            print(f"{'Name':<30} {'Version':<10} {'Risk':<6} {'Verified':<10} Description")
            print("-" * 90)
            for t in templates:
                name = _truncate_text(t.name, 30)
                desc = _truncate_text(t.description, 41, default="") if t.description else ""
                print(f"{name:<30} {t.version or '1.0.0':<10} {t.risk_tier:<6} {'✓' if t.verified else '✗':<10} {desc}")
    except Exception as e:
        print(f"❌ Error listing service templates: {e}", file=sys.stderr)
        sys.exit(1)


def list_tool_templates(client: Any, output_format: str = "table") -> None:
    """List available tool templates."""
    try:
        templates = client.tools.list_available_templates()

        if output_format == "json":
            print(json.dumps([t.model_dump() for t in templates], indent=2, default=str))
        else:
            print(f"\n🔧 Available Tool Templates ({len(templates)} total):\n")
            print(f"{'Name':<30} {'Image':<40} {'Env Vars'}")
            print("-" * 90)
            for t in templates:
                name = _truncate_text(t.name, 30)
                image = _truncate_text(t.image, 40, default="None")
                env_vars = ", ".join(t.required_env_vars or []) if t.required_env_vars else "None"
                print(f"{name:<30} {image:<40} {env_vars}")
    except Exception as e:
        print(f"❌ Error listing tool templates: {e}", file=sys.stderr)
        sys.exit(1)


def _resolve_deployment_type(name: str | None) -> str:
    if isinstance(name, str) and name.lower().startswith("service-"):
        return "service"
    return "app"


def list_deployments(client: Any, deployment_type: str = "all", output_format: str = "table") -> None:
    """List current deployments."""
    deployments = []

    if deployment_type in ["all", "apps", "services"]:
        try:
            app_deployments = client.apps.list_deployments()
            for deployment in app_deployments:
                dtype = _resolve_deployment_type(getattr(deployment, "name", None))
                if deployment_type == "apps" and dtype != "app":
                    continue
                if deployment_type == "services" and dtype != "service":
                    continue
                deployments.append((dtype, deployment))
        except Exception as e:
            print(f"⚠️  Warning: Could not list app deployments: {e}", file=sys.stderr)

    if deployment_type in ["all", "tools"]:
        try:
            tool_deployments = client.tools.list_deployments()
            deployments.extend([("tool", d) for d in tool_deployments])
        except Exception as e:
            print(f"⚠️  Warning: Could not list tool deployments: {e}", file=sys.stderr)

    if output_format == "json":
        output = {
            "apps": [d[1].model_dump() for d in deployments if d[0] == "app"],
            "services": [d[1].model_dump() for d in deployments if d[0] == "service"],
            "tools": [d[1].model_dump() for d in deployments if d[0] == "tool"],
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print(f"\n🚀 Current Deployments ({len(deployments)} total):\n")
        if not deployments:
            print("No deployments found.")
        else:
            print(f"{'Type':<6} {'Name':<30} {'Status':<12} {'ID'}")
            print("-" * 80)
            for dtype, d in deployments:
                name = _truncate_text(getattr(d, "name", None), 30)
                status = _display_text(getattr(d, "status", None), default="unknown")
                deployment_id = _display_text(getattr(d, "id", None), default="n/a")
                print(f"{dtype:<6} {name:<30} {status:<12} {deployment_id}")


def inspect_template(client: Any, template_type: str, template_name: str) -> None:
    """Inspect a template's details from Kamiwaza."""
    try:
        if template_type in ["app", "service"]:
            templates = client.apps.list_templates()
            template = next(
                (
                    t
                    for t in templates
                    if t.name == template_name
                    and _resolve_template_type(t.name, getattr(t, "template_type", None)) == template_type
                ),
                None,
            )
        else:
            templates = client.tools.list_imported_templates()
            template = next((t for t in templates if t.name == template_name), None)

        if not template:
            print(f"❌ Error: Template '{template_name}' not found")
            sys.exit(1)

        print(f"\n📋 Template Details: {template_name}\n")
        print(f"{'=' * 60}")
        print(f"Type:        {template_type}")
        print(f"Name:        {template.name}")
        print(f"Version:     {template.version}")
        print(f"Risk Tier:   {template.risk_tier}")
        print(f"Verified:    {'✅' if template.verified else '❌'}")
        if hasattr(template, "description") and template.description:
            print(f"Description: {template.description}")
        if hasattr(template, "source_type"):
            print(f"Source Type: {template.source_type}")
        if hasattr(template, "visibility"):
            print(f"Visibility:  {template.visibility}")
        print(f"{'=' * 60}\n")

        # Show full JSON if requested
        print("Full template data (JSON):")
        print(json.dumps(template.model_dump(), indent=2, default=str))

    except Exception as e:
        print(f"❌ Error inspecting template: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Manage Kamiwaza templates")
    parser.add_argument(
        "--base-url",
        default=os.getenv("KAMIWAZA_API_URL", "https://localhost/api"),
        help=("Kamiwaza API base URL (default: $KAMIWAZA_API_URL or https://localhost/api)"),
    )
    parser.add_argument(
        "--sync-base-url",
        default=os.getenv("KAMIWAZA_REMOTE_TEMPLATE_BASE_URL", "https://localhost:44443"),
        help=("Remote template base URL (default: $KAMIWAZA_REMOTE_TEMPLATE_BASE_URL or https://localhost:44443)"),
    )
    parser.add_argument(
        "--sync-apps-path",
        default=os.getenv("KAMIWAZA_REMOTE_TEMPLATE_APPS_PATH", "/apps.json"),
        help=("Remote template apps path (default: $KAMIWAZA_REMOTE_TEMPLATE_APPS_PATH or /apps.json)"),
    )
    parser.add_argument(
        "--sync-tools-path",
        default=os.getenv("KAMIWAZA_REMOTE_TEMPLATE_TOOLS_PATH", "/tools.json"),
        help=("Remote template tools path (default: $KAMIWAZA_REMOTE_TEMPLATE_TOOLS_PATH or /tools.json)"),
    )
    parser.add_argument(
        "--username",
        default=os.getenv("KAMIWAZA_USERNAME"),
        help="Username for authentication (default: $KAMIWAZA_USERNAME)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("KAMIWAZA_PASSWORD"),
        help="Password for authentication (default: $KAMIWAZA_PASSWORD)",
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Skip authentication (for public endpoints)",
    )
    parser.add_argument(
        "--repo-version",
        default=None,
        help="Registry repo version (1, 2, 3). Auto-detected from .repo-version if not specified.",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # List commands
    list_parser = subparsers.add_parser("list", help="List templates or deployments")
    list_parser.add_argument(
        "target",
        choices=["apps", "services", "tools", "all", "deployments"],
        help="What to list",
    )

    # Garden push commands
    garden_push_parser = subparsers.add_parser(
        "garden-push",
        help="Push a local app, service, or tool template to Kamiwaza Garden",
    )
    garden_push_parser.add_argument("type", choices=["app", "service", "tool"], help="Extension type")
    garden_push_parser.add_argument("name", help="Extension name")
    garden_push_parser.add_argument("--template-id", help="Optional template ID to force update")
    garden_push_parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Skip authentication (for systems with KAMIWAZA_USE_AUTH=false)",
    )

    garden_list_parser = subparsers.add_parser("garden-list", help="List App Garden templates from Kamiwaza")
    garden_list_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )
    garden_list_parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Skip authentication (for systems with KAMIWAZA_USE_AUTH=false)",
    )

    # Garden sync command
    garden_sync_parser = subparsers.add_parser("garden-sync", help="Sync remote Kamiwaza Garden templates")
    garden_sync_parser.add_argument(
        "names",
        nargs="*",
        help="Optional list of template names to sync (defaults to all)",
    )

    # Inspect command
    inspect_parser = subparsers.add_parser("inspect", help="Inspect template details")
    inspect_parser.add_argument("type", choices=["app", "service", "tool"], help="Template type")
    inspect_parser.add_argument("name", help="Template name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Re-initialize registry paths if --repo-version was explicitly provided
    if args.repo_version:
        global REGISTRY_ROOT, APPS_REGISTRY_FILE, TOOLS_REGISTRY_FILE, _DETECTED_VERSION
        REGISTRY_ROOT, _DETECTED_VERSION = _get_registry_root(args.repo_version)
        APPS_REGISTRY_FILE = REGISTRY_ROOT / "apps.json"
        TOOLS_REGISTRY_FILE = REGISTRY_ROOT / "tools.json"

    # Execute garden-specific commands before initializing the SDK client
    if args.command == "garden-push":
        if args.type == "app":
            garden_push_app_template(
                args.base_url,
                args.username,
                args.password,
                args.name,
                args.template_id,
                skip_auth=args.no_auth,
            )
        elif args.type == "service":
            garden_push_app_template(
                args.base_url,
                args.username,
                args.password,
                args.name,
                args.template_id,
                skip_auth=args.no_auth,
                extension_dir="services",
                default_template_type="service",
            )
        elif args.type == "tool":
            garden_push_tool_template(
                args.base_url,
                args.username,
                args.password,
                args.name,
                args.template_id,
                skip_auth=args.no_auth,
            )
        return

    if args.command == "garden-sync":
        sync_names = args.names if args.names else None
        skip_auth = getattr(args, "no_auth", False)
        garden_sync_templates(
            args.base_url,
            args.username,
            args.password,
            sync_names,
            args.sync_base_url,
            args.sync_apps_path,
            args.sync_tools_path,
            skip_auth=skip_auth,
        )
        return

    if args.command == "garden-list":
        skip_auth = getattr(args, "no_auth", False)
        garden_list_templates(
            args.base_url,
            args.username,
            args.password,
            args.format,
            skip_auth=skip_auth,
        )
        return

    # Initialize SDK client for remaining commands
    if args.no_auth:
        client = get_client(args.base_url)
    else:
        client = get_client(args.base_url, args.username, args.password)

    if args.command == "list":
        if args.target == "apps":
            list_app_templates(client, args.format)
        elif args.target == "services":
            list_service_templates(client, args.format)
        elif args.target == "tools":
            list_tool_templates(client, args.format)
        elif args.target == "all":
            list_app_templates(client, args.format)
            if args.format == "table":
                print()  # Add spacing between tables
            list_service_templates(client, args.format)
            if args.format == "table":
                print()
            list_tool_templates(client, args.format)
        elif args.target == "deployments":
            list_deployments(client, "all", args.format)

    elif args.command == "inspect":
        inspect_template(client, args.type, args.name)


if __name__ == "__main__":
    main()
