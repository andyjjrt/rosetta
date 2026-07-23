from __future__ import annotations

import logging

import httpx
import pytest
from pydantic import SecretStr
from starlette.types import Receive, Scope, Send

from rosetta.mcp import protect_mcp_app
from rosetta.utils.config import McpSetting

pytestmark = pytest.mark.anyio

SECRET = "private-test-token-that-is-long-enough"
ALLOWED_HOST = "mcp.local"
SENTINEL_BODY = b"\x00mcp-sentinel-ok"


class SentinelApp:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.calls += 1
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/octet-stream")],
            }
        )
        await send({"type": "http.response.body", "body": SENTINEL_BODY})


def guarded_app(sentinel: SentinelApp) -> httpx.ASGITransport:
    settings = McpSetting(
        BEARER_TOKEN=SecretStr(SECRET),
        ALLOWED_HOSTS=[ALLOWED_HOST],
        _env_file=None,
    )
    return httpx.ASGITransport(app=protect_mcp_app(sentinel, settings))


async def request_with(
    transport: httpx.ASGITransport,
    *,
    host: str = ALLOWED_HOST,
    authorization: str | None = f"Bearer {SECRET}",
) -> httpx.Response:
    headers = {"host": host}
    if authorization is not None:
        headers["authorization"] = authorization
    async with httpx.AsyncClient(
        transport=transport,
        base_url=f"http://{host}",
    ) as client:
        return await client.post("/mcp", headers=headers, content=b"{}")


async def test_valid_bearer_and_allowed_host_reaches_sentinel() -> None:
    # Given: a guarded MCP app with a private bearer token and one allowed host.
    sentinel = SentinelApp()
    transport = guarded_app(sentinel)

    # When: the request has exactly Authorization: Bearer <token> and an allowed Host.
    response = await request_with(transport)

    # Then: the downstream ASGI app handles the request and returns its binary marker.
    assert response.status_code == 200
    assert response.content == SENTINEL_BODY
    assert sentinel.calls == 1


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        SECRET,
        f"Basic {SECRET}",
        "Bearer",
        "Bearer ",
        f"Bearer {SECRET} extra",
        f"Bearer Bearer {SECRET}",
        "bearer " + SECRET,
        "Bearer wrong-token-that-is-long-enough",
    ],
)
async def test_missing_malformed_or_wrong_bearer_returns_challenge(
    authorization: str | None,
) -> None:
    # Given: a guarded MCP app whose downstream sentinel must not see bad credentials.
    sentinel = SentinelApp()
    transport = guarded_app(sentinel)

    # When: the Authorization header is missing, malformed, or has the wrong token.
    response = await request_with(transport, authorization=authorization)

    # Then: the boundary returns a Bearer challenge without dispatching downstream.
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.content == b"Unauthorized"
    assert sentinel.calls == 0


async def test_hostile_host_is_rejected_before_sentinel() -> None:
    # Given: a valid bearer token but a Host outside the configured allowlist.
    sentinel = SentinelApp()
    transport = guarded_app(sentinel)

    # When: the request presents a hostile Host header.
    response = await request_with(transport, host="evil.example")

    # Then: TrustedHostMiddleware rejects it before MCP dispatch.
    assert response.status_code in {400, 421}
    assert sentinel.calls == 0


async def test_secret_never_appears_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    # Given: log capture around failed auth requests.
    sentinel = SentinelApp()
    transport = guarded_app(sentinel)
    caplog.set_level(logging.DEBUG)

    # When: an incorrect token is rejected.
    response = await request_with(transport, authorization="Bearer wrong-token")

    # Then: the secret is absent from all captured log records and response bytes.
    assert response.status_code == 401
    assert SECRET not in caplog.text
    assert SECRET.encode() not in response.content
    assert sentinel.calls == 0
