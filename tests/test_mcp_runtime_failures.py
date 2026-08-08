from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Never

import anyio
import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.routing import Mount

from rosetta.mcp.server import create_mcp_server
from rosetta.models.music import (
    PlayRequest,
    PlayResult,
    PlaySuccess,
    SearchResult,
    SearchSuccess,
    TrackSummary,
)
from rosetta.utils.config import McpSetting

pytestmark = pytest.mark.anyio

SECRET = "private-test-token-that-is-long-enough"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(slots=True)
class DeterministicMusicService:
    async def search(self, keyword: str, limit: int = 10) -> SearchResult:
        return SearchSuccess(
            tracks=(
                TrackSummary(
                    title="Song",
                    author="Artist",
                    duration_ms=1234,
                    uri="https://example.test/watch?v=1",
                    thumbnail=None,
                ),
            )
        )

    async def play(self, request: PlayRequest) -> PlayResult:
        return PlaySuccess(
            playback_status="started",
            title="Song",
            uri=request.url,
            thumbnail=None,
            enqueued_count=1,
            node_name="MAIN",
        )


@dataclass(slots=True)
class NeverReadyUvicornServer:
    config: uvicorn.Config
    started: bool = False
    should_exit: bool = False
    served_sockets: list[socket.socket] = field(default_factory=list)

    async def serve(self, sockets: list[socket.socket]) -> None:
        self.served_sockets.extend(sockets)
        while not self.should_exit:
            await anyio.sleep(0)


@dataclass(slots=True)
class ExitingUvicornServer:
    config: uvicorn.Config
    started: bool = False
    should_exit: bool = False
    served_sockets: list[socket.socket] = field(default_factory=list)

    async def serve(self, sockets: list[socket.socket]) -> None:
        self.served_sockets.extend(sockets)
        raise SystemExit(7)


def mcp_settings(*, port: int) -> McpSetting:
    return McpSetting(
        ENABLED=True,
        HOST="127.0.0.1",
        PORT=port,
        PATH="/mcp",
        BEARER_TOKEN=SecretStr(SECRET),
        ALLOWED_HOSTS=["127.0.0.1"],
        _env_file=None,
    )


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def retained_bound_socket(monkeypatch: pytest.MonkeyPatch, runtime) -> socket.socket:
    sock = runtime._bind_socket()

    def bind_socket() -> socket.socket:
        return sock

    monkeypatch.setattr(runtime, "_bind_socket", bind_socket)
    return sock


async def test_asgi_app_constructor_failure_closes_bound_socket_and_clears_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rosetta.mcp.runtime as runtime_module

    runtime = runtime_module.MCPRuntime(
        mcp_settings(port=reserve_port()), DeterministicMusicService()
    )
    sock = retained_bound_socket(monkeypatch, runtime)

    def fail_asgi_app() -> Never:
        raise RuntimeError("asgi construction failed")

    monkeypatch.setattr(runtime, "_asgi_app", fail_asgi_app)

    with pytest.raises(RuntimeError, match="asgi construction failed"):
        await runtime.start()

    assert sock.fileno() == -1
    assert runtime._task is None
    assert runtime._server is None
    assert runtime._socket is None


async def test_uvicorn_server_constructor_failure_closes_bound_socket_and_clears_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rosetta.mcp.runtime as runtime_module

    runtime = runtime_module.MCPRuntime(
        mcp_settings(port=reserve_port()), DeterministicMusicService()
    )
    sock = retained_bound_socket(monkeypatch, runtime)

    def fail_server(_config: uvicorn.Config) -> Never:
        raise RuntimeError("uvicorn construction failed")

    monkeypatch.setattr(runtime_module.uvicorn, "Server", fail_server)

    with pytest.raises(RuntimeError, match="uvicorn construction failed"):
        await runtime.start()

    assert sock.fileno() == -1
    assert runtime._task is None
    assert runtime._server is None
    assert runtime._socket is None


async def test_cancelled_start_cleans_server_task_and_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rosetta.mcp.runtime as runtime_module

    servers: list[NeverReadyUvicornServer] = []

    def server_factory(config: uvicorn.Config) -> NeverReadyUvicornServer:
        server = NeverReadyUvicornServer(config)
        servers.append(server)
        return server

    monkeypatch.setattr(runtime_module.uvicorn, "Server", server_factory)
    runtime = runtime_module.MCPRuntime(
        mcp_settings(port=reserve_port()), DeterministicMusicService()
    )
    start_task = asyncio.create_task(runtime.start())
    try:
        with anyio.fail_after(1):
            while runtime._task is None or not servers or not servers[0].served_sockets:
                await anyio.sleep(0)
        served_socket = servers[0].served_sockets[0]

        start_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start_task

        assert runtime._task is None
        assert runtime._server is None
        assert runtime._socket is None
        assert servers[0].should_exit
        assert served_socket.fileno() == -1
    finally:
        await runtime.stop()
        if not start_task.done():
            start_task.cancel()


async def test_system_exit_from_server_task_becomes_startup_error_without_loop_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rosetta.mcp.runtime as runtime_module

    loop = asyncio.get_running_loop()
    contexts: list[str] = []
    servers: list[ExitingUvicornServer] = []
    previous_handler = loop.get_exception_handler()

    def exception_handler(
        _loop: asyncio.AbstractEventLoop,
        context: dict[str, str | BaseException],
    ) -> None:
        contexts.append(str(context.get("message", "")))

    def server_factory(config: uvicorn.Config) -> ExitingUvicornServer:
        server = ExitingUvicornServer(config)
        servers.append(server)
        return server

    monkeypatch.setattr(runtime_module.uvicorn, "Server", server_factory)
    loop.set_exception_handler(exception_handler)
    runtime = runtime_module.MCPRuntime(
        mcp_settings(port=reserve_port()), DeterministicMusicService()
    )
    try:
        with pytest.raises(runtime_module.MCPRuntimeStartupError):
            await runtime.start()
        await anyio.sleep(0)

        assert contexts == []
        assert servers[0].served_sockets[0].fileno() == -1
        assert runtime._task is None
        assert runtime._server is None
        assert runtime._socket is None
    finally:
        loop.set_exception_handler(previous_handler)
        await runtime.stop()


async def test_streamable_http_asgi_flow_closes_without_sse_resource_warning() -> None:
    mcp = create_mcp_server(DeterministicMusicService(), streamable_http_path="/")
    inner = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = Starlette(routes=[Mount("/mcp", app=inner)], lifespan=lifespan)
    async with mcp.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8000",
        ) as client:
            async with streamable_http_client(
                "http://127.0.0.1:8000/mcp/",
                http_client=client,
            ) as (read_stream, write_stream, _session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    result = await session.call_tool("search", {"keyword": "test"})
                    uri = result.structuredContent["result"]["tracks"][0]["uri"]
                    await session.call_tool(
                        "play",
                        {"user_id": "1", "chat_channel_id": "2", "url": uri},
                    )

    assert [tool.name for tool in tools.tools] == ["search", "play"]


async def test_streamable_http_asgi_flow_accepts_configured_host() -> None:
    mcp = create_mcp_server(
        DeterministicMusicService(),
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["host.docker.internal:*"],
        ),
    )
    inner = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = Starlette(routes=[Mount("/mcp", app=inner)], lifespan=lifespan)
    async with mcp.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://host.docker.internal:8000",
            headers={"Host": "host.docker.internal:8000"},
        ) as client:
            async with streamable_http_client(
                "http://host.docker.internal:8000/mcp/",
                http_client=client,
            ) as (read_stream, write_stream, _session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()

    assert [tool.name for tool in tools.tools] == ["search", "play"]


async def test_streamable_http_asgi_flow_rejects_unlisted_host_with_sdk_status() -> (
    None
):
    """FastMCP transport security reports an unlisted Host header as 421."""
    mcp = create_mcp_server(
        DeterministicMusicService(),
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["host.docker.internal:*"],
        ),
    )
    inner = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = Starlette(routes=[Mount("/mcp", app=inner)], lifespan=lifespan)
    async with mcp.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://evil.example:8000",
            headers={"Host": "evil.example:8000"},
        ) as client:
            response = await client.post(
                "/mcp/",
                headers={"Content-Type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {},
                },
            )

    assert response.status_code == 421


async def test_streamable_http_asgi_flow_accepts_configured_origin() -> None:
    mcp = create_mcp_server(
        DeterministicMusicService(),
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["host.docker.internal:*"],
            allowed_origins=["http://host.docker.internal:*"],
        ),
    )
    inner = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = Starlette(routes=[Mount("/mcp", app=inner)], lifespan=lifespan)
    async with mcp.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://host.docker.internal:8000",
            headers={
                "Host": "host.docker.internal:8000",
                "Origin": "http://host.docker.internal:8000",
            },
        ) as client:
            async with streamable_http_client(
                "http://host.docker.internal:8000/mcp/",
                http_client=client,
            ) as (read_stream, write_stream, _session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()

    assert [tool.name for tool in tools.tools] == ["search", "play"]


async def test_streamable_http_asgi_flow_rejects_unlisted_origin_with_sdk_status() -> (
    None
):
    """FastMCP transport security reports an unlisted Origin header as 403."""
    mcp = create_mcp_server(
        DeterministicMusicService(),
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["host.docker.internal:*"],
            allowed_origins=["http://host.docker.internal:*"],
        ),
    )
    inner = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = Starlette(routes=[Mount("/mcp", app=inner)], lifespan=lifespan)
    async with mcp.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://host.docker.internal:8000",
            headers={
                "Host": "host.docker.internal:8000",
                "Origin": "http://evil.example:8000",
            },
        ) as client:
            response = await client.post(
                "/mcp/",
                headers={"Content-Type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {},
                },
            )

    assert response.status_code == 403
