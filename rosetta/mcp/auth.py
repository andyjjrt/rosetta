from __future__ import annotations

import secrets
from typing import Final

from pydantic import SecretStr
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rosetta.utils.config import McpSetting

AUTHORIZATION_HEADER: Final = b"authorization"
BEARER_PREFIX: Final = "Bearer "
WWW_AUTHENTICATE_HEADER: Final = (b"www-authenticate", b"Bearer")
UNAUTHORIZED_BODY: Final = b"Unauthorized"


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, token: SecretStr) -> None:
        self._app = app
        self._token = token.get_secret_value()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        authorization = _authorization_header(scope)
        if _has_valid_bearer(authorization, self._token):
            await self._app(scope, receive, send)
            return

        await _send_unauthorized(send)


def protect_mcp_app(app: ASGIApp, settings: McpSetting) -> ASGIApp:
    token = settings.BEARER_TOKEN
    if token is None:
        settings.validate_startup()
        token = SecretStr("")

    guarded = BearerAuthMiddleware(app, token)
    return TrustedHostMiddleware(guarded, allowed_hosts=settings.ALLOWED_HOSTS)


def _authorization_header(scope: Scope) -> bytes | None:
    found: bytes | None = None
    for name, value in scope["headers"]:
        if name.lower() != AUTHORIZATION_HEADER:
            continue
        if found is not None:
            return None
        found = value
    return found


def _has_valid_bearer(header: bytes | None, token: str) -> bool:
    if header is None:
        return False
    try:
        value = header.decode("ascii")
    except UnicodeDecodeError:
        return False
    if not value.startswith(BEARER_PREFIX):
        return False
    credential = value.removeprefix(BEARER_PREFIX)
    if not credential or " " in credential:
        return False
    return secrets.compare_digest(credential, token)


async def _send_unauthorized(send: Send) -> None:
    start: Message = {
        "type": "http.response.start",
        "status": 401,
        "headers": [WWW_AUTHENTICATE_HEADER],
    }
    body: Message = {"type": "http.response.body", "body": UNAUTHORIZED_BODY}
    await send(start)
    await send(body)
