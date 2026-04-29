"""Auth resolution chain.

Priority:
  1. Explicit credentials (pass-thru)
  2. ~/.aws/credentials (pass-thru)
  3. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from env (pass-thru)
  4. R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY from env (pass-thru)
  5. Cloudflare SSO via broker (refreshable)
"""

from __future__ import annotations

from typing import Literal

from r2_client.auth.static import StaticCredentials, get_static_credentials


def resolve_credentials(
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    session_token: str | None = None,
) -> tuple[StaticCredentials | None, Literal["static", "sso"]]:
    """Resolve credentials via the auth chain.

    Returns (credentials, method) where method is "static" or "sso".
    For static, credentials may be None if neither explicit nor env are set.
    """
    static = get_static_credentials(
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        session_token=session_token,
    )
    if static is not None:
        return static, "static"
    return None, "sso"
