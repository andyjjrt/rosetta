from __future__ import annotations

from typing import Final, Protocol

from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rosetta.utils.config import McpSetting

AUTHORIZATION_HEADER: Final = b"authorization"
BEARER_PREFIX: Final = "Bearer "
WWW_AUTHENTICATE_HEADER: Final = (b"www-authenticate", b"Bearer")
UNAUTHORIZED_BODY: Final = b"Unauthorized"


class McpApiKeyValidator(Protocol):
    async def is_valid_key(self, plaintext_key: str) -> bool: ...


class BearerAuthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        key_validator: McpApiKeyValidator | None = None,
    ) -> None:
        self._app = app
        self._key_validator = key_validator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        credential = _bearer_credential(_authorization_header(scope))
        if credential is not None and await self._is_valid_credential(credential):
            await self._app(scope, receive, send)
            return

        await _send_unauthorized(send)

    async def _is_valid_credential(self, credential: str) -> bool:
        if self._key_validator is not None:
            return await self._key_validator.is_valid_key(credential)
        return False


def protect_mcp_app(
    app: ASGIApp,
    settings: McpSetting,
    key_validator: McpApiKeyValidator | None = None,
) -> ASGIApp:
    if key_validator is None:
        settings.validate_startup()

    guarded = BearerAuthMiddleware(app, key_validator)
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


def _bearer_credential(header: bytes | None) -> str | None:
    if header is None:
        return None
    try:
        value = header.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not value.startswith(BEARER_PREFIX):
        return None
    credential = value.removeprefix(BEARER_PREFIX)
    if not credential or " " in credential:
        return None
    return credential


async def _send_unauthorized(send: Send) -> None:
    start: Message = {
        "type": "http.response.start",
        "status": 401,
        "headers": [WWW_AUTHENTICATE_HEADER],
    }
    body: Message = {"type": "http.response.body", "body": UNAUTHORIZED_BODY}
    await send(start)
    await send(body)
