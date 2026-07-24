from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import SecretStr

from rosetta.utils.config import CogSetting, McpSetting, NanobotSetting


@dataclass(slots=True)
class CompositionRecorder:
    events: list[str] = field(default_factory=list)
    mcp_stop_error: RuntimeError | None = None
    nanobot_close_error: RuntimeError | None = None


@dataclass(slots=True)
class FakeMusic:
    bot: object
    recorder: CompositionRecorder
    service: object | None = None

    def __post_init__(self) -> None:
        self.recorder.events.append("music")
        self.service = self


@dataclass(slots=True)
class FakeMCPRuntime:
    settings: McpSetting
    music: object
    recorder: CompositionRecorder
    started: bool = False
    stopped: bool = False

    async def start(self) -> None:
        self.started = True
        self.recorder.events.append("mcp.start")

    async def stop(self) -> None:
        if self.stopped:
            self.recorder.events.append("mcp.stop.again")
            return
        self.stopped = True
        self.recorder.events.append("mcp.stop")
        if self.recorder.mcp_stop_error is not None:
            raise self.recorder.mcp_stop_error


@dataclass(slots=True)
class FakeNanobotClient:
    recorder: CompositionRecorder
    closed: bool = False

    async def aclose(self) -> None:
        if self.closed:
            self.recorder.events.append("client.close.again")
            return
        self.closed = True
        self.recorder.events.append("client.close")


@dataclass(slots=True)
class FakeNanobotCog:
    bot: object
    policy_repository: object
    client: FakeNanobotClient
    recorder: CompositionRecorder
    closed: bool = False

    async def aclose(self) -> None:
        if self.closed:
            self.recorder.events.append("nanobot.close.again")
            return
        self.closed = True
        self.recorder.events.append("nanobot.close")
        if self.recorder.nanobot_close_error is not None:
            raise self.recorder.nanobot_close_error
        await self.client.aclose()


def mcp_settings(*, enabled: bool = False) -> McpSetting:
    return McpSetting(
        ENABLED=enabled,
        BEARER_TOKEN=SecretStr("private-test-token-that-is-long-enough"),
        _env_file=None,
    )


def disabled_cogs() -> CogSetting:
    return CogSetting(
        BASICS_DISABLE=True,
        MUSIC_DISABLE=True,
        MYGO_DISABLE=True,
        LLM_DISABLE=True,
        _env_file=None,
    )


def nanobot_enabled_cogs(*, music_enabled: bool = True) -> CogSetting:
    return CogSetting(
        BASICS_DISABLE=True,
        MUSIC_DISABLE=not music_enabled,
        MYGO_DISABLE=True,
        LLM_DISABLE=True,
        NANOBOT_DISABLE=False,
        _env_file=None,
    )


def nanobot_settings(tmp_path: Path) -> NanobotSetting:
    config_path = tmp_path / "nanobot.json"
    config_path.write_text("{}", encoding="utf-8")
    return NanobotSetting(
        CONFIG_PATH=config_path,
        POLICY_PATH=tmp_path / "guild-policies.json",
        MAX_CONCURRENT_RUNS=2,
        _env_file=None,
    )


def import_composition() -> ModuleType:
    sys.modules.pop("rosetta.__main__", None)
    return importlib.import_module("rosetta.__main__")


def install_fake_music(
    monkeypatch: pytest.MonkeyPatch, recorder: CompositionRecorder
) -> None:
    music_module = ModuleType("rosetta.commands.music")

    class Music(FakeMusic):
        def __init__(self, bot: object) -> None:
            super().__init__(bot=bot, recorder=recorder)

    music_module.Music = Music
    monkeypatch.setitem(sys.modules, "rosetta.commands.music", music_module)


def install_fake_nanobot(
    monkeypatch: pytest.MonkeyPatch,
    recorder: CompositionRecorder,
    *,
    create_fails: RuntimeError | None = None,
    cog_fails: RuntimeError | None = None,
) -> None:
    nanobot_module = ModuleType("rosetta.commands.nanobot")
    client_module = ModuleType("rosetta.utils.nanobot_client")

    class Nanobot(FakeNanobotCog):
        def __init__(
            self, bot: object, policy_repository: object, client: FakeNanobotClient
        ) -> None:
            if cog_fails is not None:
                recorder.events.append("nanobot.cog")
                raise cog_fails
            super().__init__(
                bot=bot,
                policy_repository=policy_repository,
                client=client,
                recorder=recorder,
            )

    class NanobotSdkClient:
        @classmethod
        def create(cls, settings: NanobotSetting) -> FakeNanobotClient:
            recorder.events.append("nanobot.create")
            if create_fails is not None:
                raise create_fails
            return FakeNanobotClient(recorder=recorder)

    nanobot_module.Nanobot = Nanobot
    client_module.NanobotSdkClient = NanobotSdkClient
    monkeypatch.setitem(sys.modules, "rosetta.commands.nanobot", nanobot_module)
    monkeypatch.setitem(sys.modules, "rosetta.utils.nanobot_client", client_module)


def install_fake_mcp(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, recorder: CompositionRecorder
) -> None:
    class Runtime(FakeMCPRuntime):
        def __init__(self, settings: McpSetting, music: object) -> None:
            super().__init__(settings=settings, music=music, recorder=recorder)

    monkeypatch.setattr(module, "MCPRuntime", Runtime)


def install_add_cog_recorder(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    recorder: CompositionRecorder,
    *,
    fail_nanobot_add: RuntimeError | None = None,
) -> None:
    async def add_cog(self, cog: object) -> None:
        if isinstance(cog, FakeNanobotCog):
            recorder.events.append("add_cog")
            if fail_nanobot_add is not None:
                raise fail_nanobot_add
            self._nanobot_added = cog

    monkeypatch.setattr(module.commands.Bot, "add_cog", add_cog)


def install_discord_close_recorder(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    recorder: CompositionRecorder,
) -> None:
    async def close_discord(_self) -> None:
        recorder.events.append("discord.close")

    monkeypatch.setattr(module.commands.Bot, "close", close_discord)
