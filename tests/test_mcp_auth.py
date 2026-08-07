from __future__ import annotations

# allow: SIZE_OK — comprehensive MCP auth edge-case matrix is intentionally co-located.
import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

import httpx
import pytest
from starlette.types import Receive, Scope, Send

from rosetta.mcp import protect_mcp_app
from rosetta.utils.config import McpSetting
from rosetta.utils.mcp_api_keys import KEY_VISIBLE_PREFIX_LENGTH, McpApiKeyRepository

pytestmark = pytest.mark.anyio

SECRET = "private-test-token-that-is-long-enough"
ALLOWED_HOST = "mcp.local"
SENTINEL_BODY = b"\x00mcp-sentinel-ok"
STATIC_TEST_KEY_NAME: Final = "static-test-token"


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


async def guarded_app(
    sentinel: SentinelApp,
    tmp_path: Path,
    *,
    key_validator: McpApiKeyRepository | None = None,
    plaintext_key: str | None = SECRET,
) -> httpx.ASGITransport:
    repository = (
        key_validator if key_validator is not None else managed_key_repository(tmp_path)
    )
    if plaintext_key is not None:
        await create_managed_key(repository, STATIC_TEST_KEY_NAME, plaintext_key)
    settings = McpSetting(
        BEARER_TOKEN=None,
        ALLOWED_HOSTS=[ALLOWED_HOST],
        _env_file=None,
    )
    return httpx.ASGITransport(app=protect_mcp_app(sentinel, settings, repository))


def managed_key_repository(tmp_path: Path) -> McpApiKeyRepository:
    return McpApiKeyRepository(tmp_path / "settings.sqlite3")


async def create_managed_key(
    repository: McpApiKeyRepository,
    name: str,
    plaintext_key: str,
) -> None:
    await repository.create(name)
    key_hash = hashlib.sha256(plaintext_key.encode("ascii")).hexdigest()
    with repository._database.connect() as connection:
        connection.execute(
            """UPDATE mcp_api_keys
            SET key_hash = ?, key_prefix = ?, fingerprint = ?
            WHERE name = ?""",
            (
                key_hash,
                plaintext_key[:KEY_VISIBLE_PREFIX_LENGTH],
                key_hash[:KEY_VISIBLE_PREFIX_LENGTH],
                name,
            ),
        )


def assert_unauthorized(response: httpx.Response, sentinel: SentinelApp) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.content == b"Unauthorized"
    assert sentinel.calls == 0


@asynccontextmanager
async def mcp_client(
    transport: httpx.ASGITransport,
    host: str,
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=transport,
        base_url=f"http://{host}",
    ) as client:
        yield client


async def request_with(
    transport: httpx.ASGITransport,
    *,
    host: str = ALLOWED_HOST,
    authorization: str | None = f"Bearer {SECRET}",
) -> httpx.Response:
    headers = {"host": host}
    if authorization is not None:
        headers["authorization"] = authorization
    async with mcp_client(transport, host) as client:
        return await client.post("/mcp", headers=headers, content=b"{}")


async def request_with_header_pairs(
    transport: httpx.ASGITransport,
    headers: list[tuple[str, str]],
    *,
    host: str = ALLOWED_HOST,
) -> httpx.Response:
    async with mcp_client(transport, host) as client:
        return await client.post(
            "/mcp",
            headers=[("host", host), *headers],
            content=b"{}",
        )


async def request_with_raw_header_pairs(
    transport: httpx.ASGITransport,
    headers: list[tuple[bytes, bytes]],
    *,
    host: str = ALLOWED_HOST,
) -> httpx.Response:
    async with mcp_client(transport, host) as client:
        return await client.post(
            "/mcp",
            headers=[(b"host", host.encode("ascii")), *headers],
            content=b"{}",
        )


async def test_valid_bearer_and_allowed_host_reaches_sentinel(tmp_path: Path) -> None:
    # Given: a guarded MCP app with a private bearer token and one allowed host.
    sentinel = SentinelApp()
    transport = await guarded_app(sentinel, tmp_path)

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
    tmp_path: Path,
) -> None:
    # Given: a guarded MCP app whose downstream sentinel must not see bad credentials.
    sentinel = SentinelApp()
    transport = await guarded_app(sentinel, tmp_path)

    # When: the Authorization header is missing, malformed, or has the wrong token.
    response = await request_with(transport, authorization=authorization)

    # Then: the boundary returns a Bearer challenge without dispatching downstream.
    assert_unauthorized(response, sentinel)


async def test_duplicate_authorization_headers_return_challenge(tmp_path: Path) -> None:
    # Given: a guarded MCP app whose downstream sentinel must not see ambiguous credentials.
    sentinel = SentinelApp()
    transport = await guarded_app(sentinel, tmp_path)

    # When: the request repeats Authorization, even with one otherwise valid bearer.
    response = await request_with_header_pairs(
        transport,
        [
            ("authorization", f"Bearer {SECRET}"),
            ("authorization", "Bearer wrong-token-that-is-long-enough"),
        ],
    )

    # Then: the auth boundary rejects the ambiguous request before MCP dispatch.
    assert_unauthorized(response, sentinel)


async def test_non_ascii_authorization_header_returns_challenge(tmp_path: Path) -> None:
    # Given: a guarded MCP app whose Authorization value must be ASCII bearer syntax.
    sentinel = SentinelApp()
    transport = await guarded_app(sentinel, tmp_path)

    # When: the credential contains a non-ASCII byte after the bearer prefix.
    response = await request_with_raw_header_pairs(
        transport,
        [(b"authorization", "Bearer café".encode())],
    )

    # Then: the boundary rejects it before MCP dispatch.
    assert_unauthorized(response, sentinel)


async def test_hostile_host_is_rejected_before_sentinel(tmp_path: Path) -> None:
    # Given: a valid bearer token but a Host outside the configured allowlist.
    sentinel = SentinelApp()
    transport = await guarded_app(sentinel, tmp_path)

    # When: the request presents a hostile Host header.
    response = await request_with(transport, host="evil.example")

    # Then: TrustedHostMiddleware rejects it before MCP dispatch.
    assert response.status_code in {400, 421}
    assert sentinel.calls == 0


async def test_secret_never_appears_in_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: log capture around failed auth requests.
    sentinel = SentinelApp()
    transport = await guarded_app(sentinel, tmp_path)
    caplog.set_level(logging.DEBUG)

    # When: an incorrect token is rejected.
    response = await request_with(transport, authorization="Bearer wrong-token")

    # Then: the secret is absent from all captured log records and response bytes.
    assert response.status_code == 401
    assert SECRET not in caplog.text
    assert SECRET.encode() not in response.content
    assert sentinel.calls == 0


async def test_managed_auth_with_zero_keys_rejects_valid_looking_bearer(
    tmp_path: Path,
) -> None:
    # Given: a guarded MCP app using an empty temporary managed-key repository.
    sentinel = SentinelApp()
    repository = managed_key_repository(tmp_path)
    transport = await guarded_app(
        sentinel, tmp_path, key_validator=repository, plaintext_key=None
    )

    # When: a client presents a syntactically valid bearer credential.
    response = await request_with(
        transport,
        authorization="Bearer rst_mcp_valid_looking_key_without_repository_match",
    )

    # Then: zero managed keys means no credential reaches the MCP app.
    assert_unauthorized(response, sentinel)


async def test_created_managed_key_reaches_sentinel(tmp_path: Path) -> None:
    # Given: a guarded MCP app using a temporary repository with one created key.
    sentinel = SentinelApp()
    repository = managed_key_repository(tmp_path)
    created = await repository.create("operator")
    transport = await guarded_app(
        sentinel, tmp_path, key_validator=repository, plaintext_key=None
    )

    # When: the request uses the generated one-time plaintext key.
    response = await request_with(
        transport,
        authorization=f"Bearer {created.plaintext_key}",
    )

    # Then: repository validation allows the downstream MCP app to handle it.
    assert response.status_code == 200
    assert response.content == SENTINEL_BODY
    assert sentinel.calls == 1


async def test_deleted_managed_key_returns_challenge(tmp_path: Path) -> None:
    # Given: a managed key that was created and then deleted before use.
    sentinel = SentinelApp()
    repository = managed_key_repository(tmp_path)
    created = await repository.create("operator")
    await repository.delete("operator")
    transport = await guarded_app(
        sentinel, tmp_path, key_validator=repository, plaintext_key=None
    )

    # When: the request still presents the deleted key's plaintext value.
    response = await request_with(
        transport,
        authorization=f"Bearer {created.plaintext_key}",
    )

    # Then: deleted keys are rejected before MCP dispatch.
    assert_unauthorized(response, sentinel)


async def test_wrong_managed_bearer_suffix_returns_constant_body_without_key_leakage(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: a generated managed key and log capture around the auth boundary.
    sentinel = SentinelApp()
    repository = managed_key_repository(tmp_path)
    created = await repository.create("operator")
    transport = await guarded_app(
        sentinel, tmp_path, key_validator=repository, plaintext_key=None
    )
    caplog.set_level(logging.DEBUG)

    # When: a client presents the generated key with extra suffix material.
    response = await request_with(
        transport,
        authorization=f"Bearer {created.plaintext_key}-wrong",
    )

    # Then: the rejection body is constant and neither response nor logs expose the key.
    assert_unauthorized(response, sentinel)
    assert response.text == "Unauthorized"
    assert created.plaintext_key not in response.text
    assert created.plaintext_key not in caplog.text


async def test_rotated_managed_key_invalidates_old_key_without_restarting_app(
    tmp_path: Path,
) -> None:
    # Given: one ASGI app instance protecting MCP with a temporary key repository.
    sentinel = SentinelApp()
    repository = managed_key_repository(tmp_path)
    created = await repository.create("operator")
    transport = await guarded_app(
        sentinel, tmp_path, key_validator=repository, plaintext_key=None
    )

    # When: the original key is used, then the same named key is rotated in-place.
    first_response = await request_with(
        transport,
        authorization=f"Bearer {created.plaintext_key}",
    )
    rotated = await repository.rotate("operator")
    old_key_response = await request_with(
        transport,
        authorization=f"Bearer {created.plaintext_key}",
    )
    new_key_response = await request_with(
        transport,
        authorization=f"Bearer {rotated.plaintext_key}",
    )

    # Then: rotation changes auth for the same protected ASGI app instance.
    assert first_response.status_code == 200
    assert old_key_response.status_code == 401
    assert old_key_response.headers["www-authenticate"] == "Bearer"
    assert new_key_response.status_code == 200
    assert new_key_response.content == SENTINEL_BODY
    assert sentinel.calls == 2
