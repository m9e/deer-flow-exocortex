"""Cloudflare auth + credential broker exchange.

Uses Cloudflare for authentication (Google SSO is integrated in Cloudflare).
Prints login URL; user opens it in browser and logs in via Cloudflare.
Uses authorization code flow with PKCE (OAuth 2.0 best practice).
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import requests

from r2_client.config import Config


def _load_template(name: str) -> str:
    """Load HTML template from package templates directory."""
    path = resources.files("r2_client.auth") / "templates" / name
    return path.read_text(encoding="utf-8")


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256).

    Returns:
        (code_verifier, code_challenge)
    """
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return code_verifier, code_challenge


def get_cloudflare_token(config: Config, bucket: str | None = None) -> str:
    """Obtain Cloudflare auth token (cached or via browser login).

    When no valid cached token exists, opens browser to broker login.
    User logs in via Cloudflare (Google SSO); broker redirects back with token.

    Args:
        config: R2 client config.
        bucket: Optional bucket name; when provided, shown on success/error pages.

    Raises:
        RuntimeError: If no valid token can be obtained.
    """
    token_path = Path(config.auth.token_cache_path).expanduser()
    token_path.parent.mkdir(parents=True, exist_ok=True)

    # Try cached token first
    cached = _load_cached_token(token_path)
    if cached and not _is_token_expired(cached):
        return cast(str, cached["token"])

    # Cloudflare login via broker (opens browser)
    token = _run_cloudflare_login(config, token_path, bucket=bucket)
    return token


def _load_cached_token(path: Path) -> dict[str, Any] | None:
    """Load cached token from disk."""
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return cast(dict[str, Any], json.load(f))
    except (json.JSONDecodeError, OSError):
        return None


def _is_token_expired(cached: dict[str, Any]) -> bool:
    """Check if cached token is expired (best-effort).

    Uses expires_at from cache, or decodes JWT exp claim if present.
    Expiry is dictated by the Cloudflare Access application's session config.
    """
    expiry = cached.get("expires_at")
    if expiry:
        try:
            from datetime import datetime, timezone

            exp = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) >= exp
        except (ValueError, TypeError):
            pass
    # Fallback: decode JWT exp claim (Cloudflare Access dictates session lifetime)
    token = cached.get("token")
    if token:
        exp_ts = _jwt_exp_claim(token)
        if exp_ts is not None:
            import time

            return time.time() >= exp_ts
    return False


def _jwt_exp_claim(token: str) -> int | None:
    """Extract exp (expiration) claim from JWT payload without verification."""
    try:
        import base64

        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        # base64url: replace - with +, _ with /
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        payload = payload.replace("-", "+").replace("_", "/")
        data = json.loads(base64.b64decode(payload).decode())
        return cast(int | None, data.get("exp"))
    except (ValueError, KeyError, TypeError):
        return None


def _run_cloudflare_login(config: Config, token_path: Path, bucket: str | None = None) -> str:
    """Open browser to broker login; receive code via localhost callback; exchange for token."""
    broker_url = config.r2.broker_url
    if not broker_url:
        raise RuntimeError(
            "Broker URL not configured. Set R2_BROKER_URL in your environment. "
            "This is typically set by your organization for Cloudflare R2 access."
        )

    code_verifier, code_challenge = _generate_pkce_pair()
    port = _find_free_port()
    redirect_uri = f"http://localhost:{port}/callback"
    if bucket:
        redirect_uri += f"?bucket={bucket}"

    code_received: list[str] = []
    error_received: list[str] = []
    bucket_received: list[str] = []

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/callback":
                params = parse_qs(parsed.query)
                if "code" in params:
                    code_received.append(params["code"][0])
                elif "error" in params:
                    error_received.append(params["error"][0])
                if "bucket" in params:
                    bucket_received.append(params["bucket"][0])
            self._send_response()

        def _send_response(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            display_bucket = bucket_received[0] if bucket_received else bucket
            bucket_label = f" for {display_bucket}" if display_bucket else ""
            if code_received:
                body = _load_template("callback_success.html").replace("{{bucket_label}}", bucket_label)
            elif error_received:
                body = (
                    _load_template("callback_error.html")
                    .replace("{{error}}", html.escape(error_received[0]))
                    .replace("{{bucket_label}}", bucket_label)
                )
            else:
                body = _load_template("callback_no_code.html").replace("{{bucket_label}}", bucket_label)
            self.wfile.write(body.encode())

        def log_message(self, format_str: str, *args: Any) -> None:
            pass  # Suppress server logs (BaseHTTPRequestHandler override)

    login_url = (
        f"{broker_url.rstrip('/')}/login"
        f"?redirect_uri={redirect_uri}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    sep = "=" * 72
    print(
        f"\n{sep}\n"
        f"  CLOUDFLARE LOGIN REQUIRED\n"
        f"  Open this URL in your browser to authenticate:\n"
        f"\n  {login_url}\n"
        f"{sep}\n",
        flush=True,
    )

    with HTTPServer(("127.0.0.1", port), CallbackHandler) as httpd:
        httpd.handle_request()

    if error_received:
        raise RuntimeError(f"Cloudflare login failed: {error_received[0]}")

    if not code_received:
        raise RuntimeError(
            "Cloudflare login did not complete. Please try again. "
            "Ensure your broker is configured for Cloudflare Access with Google SSO."
        )

    token = _exchange_code_for_token(
        code=code_received[0],
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        broker_url=broker_url,
    )
    _save_token(token_path, token, config.defaults.credential_ttl_seconds)
    return token


def _exchange_code_for_token(
    code: str,
    code_verifier: str,
    redirect_uri: str,
    broker_url: str,
) -> str:
    """Exchange authorization code for JWT (PKCE flow)."""
    resp = requests.post(
        broker_url.rstrip("/") + "/token",
        json={
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    try:
        data = resp.json()
    except requests.exceptions.JSONDecodeError as e:
        body_preview = (resp.text or "")[:200]
        raise RuntimeError(
            f"Broker /token returned non-JSON (status {resp.status_code}). "
            f"Ensure Cloudflare Access has a Bypass policy for s3.kamiwaza.ai/token. "
            f"Response preview: {body_preview!r}"
        ) from e
    token = data.get("token")
    if not token:
        raise RuntimeError("Broker did not return a token")
    return cast(str, token)


def _save_token(path: Path, token: str, fallback_ttl_seconds: int = 900) -> None:
    """Save token to disk with secure permissions.

    Expiry is dictated by the Cloudflare Access JWT exp claim when decodable;
    otherwise falls back to fallback_ttl_seconds.
    """
    from datetime import datetime, timezone

    path.parent.mkdir(parents=True, exist_ok=True)
    exp_ts = _jwt_exp_claim(token)
    if exp_ts is not None:
        expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc).isoformat()
    else:
        from datetime import timedelta

        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=fallback_ttl_seconds)).isoformat()
    data = {"token": token, "expires_at": expires_at}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(path, 0o600)


def _find_free_port() -> int:
    """Find a free port for the callback server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return cast(int, s.getsockname()[1])


def exchange_token_for_credentials(
    token: str,
    broker_url: str,
    *,
    bucket: str | None = None,
) -> dict[str, Any]:
    """Exchange Cloudflare auth token for temporary R2 credentials.

    When bucket is provided, requests credentials for that bucket. Useful when
    the user is in multiple groups (e.g. developer + ops) and the default
    role-based bucket would be prod; pass bucket='dev-kevin-test' to get
    dev credentials instead.

    Returns:
        Dict with access_key_id, secret_access_key, session_token, expiration.
    """
    payload: dict[str, Any] = {"token": token}
    if bucket:
        payload["bucket"] = bucket
    resp = requests.post(
        broker_url.rstrip("/") + "/credentials",
        json=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return cast(dict[str, Any], resp.json())
