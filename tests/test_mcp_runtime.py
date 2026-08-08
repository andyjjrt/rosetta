from __future__ import annotations

import importlib
import socket
import sys
import types
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from rosetta.models.music import (
    PlayRequest,
    PlayResult,
    PlaySuccess,
    SearchResult,
    SearchSuccess,
    TrackSummary,
)
from rosetta.utils.config import CogSetting, McpSetting
from rosetta.utils.mcp_api_keys import McpApiKeyRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(slots=True)
class DeterministicMusicService:
    search_calls: list[tuple[str, int]] = field(default_factory=list)
    play_calls: list[PlayRequest] = field(default_factory=list)

    async def search(self, keyword: str, limit: int = 10) -> SearchResult:
        self.search_calls.append((keyword, limit))
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
        self.play_calls.append(request)
        return PlaySuccess(
            playback_status="started",
            title="Song",
            uri=request.url,
            thumbnail=None,
            enqueued_count=1,
            node_name="MAIN",
        )


@dataclass(slots=True)
class CountingSessionManager:
    enters: int = 0
    exits: int = 0

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        self.enters += 1
        try:
            yield
        finally:
            self.exits += 1


@dataclass(frozen=True, slots=True)
class FakeMCPServer:
    session_manager: CountingSessionManager

    def streamable_http_app(self) -> Starlette:
        async def endpoint(request: Request) -> Response:
            return PlainTextResponse("ok")

        return Starlette(routes=[Route("/", endpoint, methods=["POST"])])


def mcp_settings(*, enabled: bool = True, port: int = 0) -> McpSetting:
    return McpSetting(
        ENABLED=enabled,
        HOST="127.0.0.1",
        PORT=port,
        PATH="/mcp",
        ALLOWED_HOSTS=["127.0.0.1"],
        _env_file=None,
    )


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def assert_refused(port: int) -> None:
    with anyio.fail_after(1):
        with pytest.raises(OSError):
            await anyio.connect_tcp("127.0.0.1", port)


async def test_disabled_start_opens_no_listener() -> None:
    from rosetta.mcp.runtime import MCPRuntime

    port = reserve_port()
    runtime = MCPRuntime(
        mcp_settings(enabled=False, port=port), DeterministicMusicService()
    )

    await runtime.start()

    await assert_refused(port)


async def test_enabled_authenticated_initialize_list_and_sentinel_are_concurrent(
    tmp_path: Path,
) -> None:
    from rosetta.mcp.runtime import MCPRuntime

    port = reserve_port()
    key_repository = McpApiKeyRepository(tmp_path / "settings.sqlite3")
    created_key = await key_repository.create("runtime-test")
    runtime = MCPRuntime(
        mcp_settings(port=port),
        DeterministicMusicService(),
        api_key_validator=key_repository,
    )

    async with anyio.create_task_group() as task_group:
        await runtime.start()
        send, receive = anyio.create_memory_object_stream[str](1)

        async def sentinel() -> None:
            async with send:
                await send.send("bot-side-progress")

        task_group.start_soon(sentinel)
        async with receive:
            with anyio.fail_after(1):
                assert await receive.receive() == "bot-side-progress"
        async with httpx.AsyncClient(
            headers={"authorization": f"Bearer {created_key.plaintext_key}"},
            timeout=5,
        ) as client:
            async with streamable_http_client(
                runtime.url + "/",
                http_client=client,
            ) as (read_stream, write_stream, _session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()

        assert [tool.name for tool in tools.tools] == ["search", "play"]
        await runtime.stop()
        await assert_refused(port)
        task_group.cancel_scope.cancel()


async def test_duplicate_start_is_rejected() -> None:
    from rosetta.mcp.runtime import MCPRuntime, MCPRuntimeAlreadyStartedError

    runtime = MCPRuntime(mcp_settings(port=reserve_port()), DeterministicMusicService())

    await runtime.start()
    try:
        with pytest.raises(MCPRuntimeAlreadyStartedError):
            await runtime.start()
    finally:
        await runtime.stop()


async def test_occupied_port_failure_propagates() -> None:
    from rosetta.mcp.runtime import MCPRuntime, MCPRuntimeStartupError

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        runtime = MCPRuntime(mcp_settings(port=port), DeterministicMusicService())

        with pytest.raises(MCPRuntimeStartupError, match=str(port)):
            await runtime.start()


async def test_sdk_lifespan_enters_and_exits_once() -> None:
    from rosetta.mcp.runtime import MCPRuntime

    manager = CountingSessionManager()

    def factory(
        _music: DeterministicMusicService,
        *,
        streamable_http_path: str,
        transport_security: TransportSecuritySettings,
    ) -> FakeMCPServer:
        assert streamable_http_path == "/"
        assert transport_security == TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*"],
            allowed_origins=["http://127.0.0.1:*"],
        )
        return FakeMCPServer(manager)

    runtime = MCPRuntime(
        mcp_settings(port=reserve_port()), DeterministicMusicService(), factory
    )
    await runtime.start()
    await runtime.stop()

    assert manager.enters == 1
    assert manager.exits == 1


async def test_stop_is_idempotent_after_listener_closed() -> None:
    from rosetta.mcp.runtime import MCPRuntime

    port = reserve_port()
    runtime = MCPRuntime(mcp_settings(port=port), DeterministicMusicService())

    await runtime.start()

    await runtime.stop()
    await runtime.stop()

    await assert_refused(port)


def install_fake_commands_module(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("rosetta.commands")

    class Basics: ...

    class LLM: ...

    class Music: ...

    class Mygo: ...

    fake.Basics = Basics
    fake.LLM = LLM
    fake.Music = Music
    fake.Mygo = Mygo
    monkeypatch.setitem(sys.modules, "rosetta.commands", fake)


def import_composition(monkeypatch: pytest.MonkeyPatch):
    install_fake_commands_module(monkeypatch)
    monkeypatch.delitem(sys.modules, "rosetta.__main__", raising=False)
    return importlib.import_module("rosetta.__main__")


def test_importing_composition_does_not_run_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    def run(self, token: str | None) -> None:
        calls.append(token)

    monkeypatch.setattr("discord.ext.commands.Bot.run", run)

    module = import_composition(monkeypatch)

    assert calls == []
    assert module.bot.command_prefix == "!"
    assert module.bot.intents.message_content
    assert module.bot.intents.guilds
    assert module.bot.intents.voice_states


def test_main_preserves_bot_run(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str | None] = []

    def run(self, token: str | None) -> None:
        calls.append(token)

    monkeypatch.setattr("discord.ext.commands.Bot.run", run)
    module = import_composition(monkeypatch)

    module.main()

    assert calls == [module.BotConfig.TOKEN]


async def test_mcp_enabled_with_music_disabled_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_composition(monkeypatch)
    bot = module.RosettaBot(
        cog_config=CogSetting(
            BASICS_DISABLE=True,
            MUSIC_DISABLE=True,
            MYGO_DISABLE=True,
            LLM_DISABLE=True,
            _env_file=None,
        ),
        mcp_config=mcp_settings(port=reserve_port()),
    )

    with pytest.raises(
        RuntimeError, match="MCP_ENABLED requires COG_MUSIC_DISABLE=false"
    ):
        await bot.setup_hook()
    await bot.close()
