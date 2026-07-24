from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Never

import pytest

from tests.nanobot_composition_fakes import (
    CompositionRecorder,
    FakeMCPRuntime,
    FakeMusic,
    disabled_cogs,
    import_composition,
    install_add_cog_recorder,
    install_discord_close_recorder,
    install_fake_mcp,
    install_fake_music,
    install_fake_nanobot,
    mcp_settings,
    nanobot_enabled_cogs,
    nanobot_settings,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def bot_with_fakes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    music_enabled: bool = True,
    mcp_enabled: bool = True,
    create_fails: RuntimeError | None = None,
    cog_fails: RuntimeError | None = None,
    fail_nanobot_add: RuntimeError | None = None,
    record_discord_close: bool = False,
    recorder: CompositionRecorder | None = None,
):
    recorder = recorder or CompositionRecorder()
    module = import_composition()
    install_fake_music(monkeypatch, recorder)
    install_fake_nanobot(
        monkeypatch,
        recorder,
        create_fails=create_fails,
        cog_fails=cog_fails,
    )
    install_fake_mcp(monkeypatch, module, recorder)
    install_add_cog_recorder(
        monkeypatch,
        module,
        recorder,
        fail_nanobot_add=fail_nanobot_add,
    )
    if record_discord_close:
        install_discord_close_recorder(monkeypatch, module, recorder)
    bot = module.RosettaBot(
        cog_config=nanobot_enabled_cogs(music_enabled=music_enabled),
        mcp_config=mcp_settings(enabled=mcp_enabled),
        nanobot_config=nanobot_settings(tmp_path),
    )
    return module, bot, recorder


async def test_disabled_nanobot_startup_does_not_import_or_create_nanobot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: Nanobot remains disabled by default and importing its module would fail.
    recorder = CompositionRecorder()
    module = import_composition()

    async def close_discord(_self) -> None:
        recorder.events.append("discord.close")

    monkeypatch.setattr(module.commands.Bot, "close", close_discord)
    monkeypatch.setitem(sys.modules, "rosetta.commands.nanobot", None)
    bot = module.RosettaBot(
        cog_config=disabled_cogs(),
        mcp_config=mcp_settings(enabled=False),
    )

    # When: setup and shutdown run with current default disabled behavior.
    await bot.setup_hook()
    await bot.close()

    # Then: no Nanobot or MCP lifecycle is touched, and Discord close still runs.
    assert recorder.events == ["discord.close"]
    assert bot._mcp_runtime is None


async def test_existing_mcp_music_dependency_failure_remains_unchanged() -> None:
    # Given: MCP is enabled while the Music cog is disabled.
    module = import_composition()
    bot = module.RosettaBot(
        cog_config=disabled_cogs(),
        mcp_config=mcp_settings(enabled=True),
    )

    # When/Then: the existing startup guard rejects it before any cog startup.
    with pytest.raises(
        RuntimeError, match="MCP_ENABLED requires COG_MUSIC_DISABLE=false"
    ):
        await bot.setup_hook()
    await bot.close()


async def test_nanobot_enabled_with_music_disabled_fails_before_starts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _module, bot, recorder = bot_with_fakes(monkeypatch, tmp_path, music_enabled=False)

    with pytest.raises(
        RuntimeError, match="COG_NANOBOT_DISABLE=false requires COG_MUSIC_DISABLE=false"
    ):
        await bot.setup_hook()

    assert recorder.events == []


async def test_nanobot_enabled_with_mcp_disabled_fails_before_starts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _module, bot, recorder = bot_with_fakes(monkeypatch, tmp_path, mcp_enabled=False)

    with pytest.raises(
        RuntimeError, match="COG_NANOBOT_DISABLE=false requires MCP_ENABLED=true"
    ):
        await bot.setup_hook()

    assert recorder.events == []


async def test_nanobot_setup_order_is_music_mcp_create_add_cog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _module, bot, recorder = bot_with_fakes(monkeypatch, tmp_path)

    await bot.setup_hook()

    assert recorder.events == ["music", "mcp.start", "nanobot.create", "add_cog"]
    assert bot._mcp_runtime is not None
    assert bot._nanobot_cog is not None


async def test_nanobot_constructor_failure_rolls_back_owned_mcp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _module, bot, recorder = bot_with_fakes(
        monkeypatch,
        tmp_path,
        create_fails=RuntimeError("nanobot construction failed"),
    )

    with pytest.raises(RuntimeError, match="nanobot construction failed"):
        await bot.setup_hook()

    assert recorder.events == ["music", "mcp.start", "nanobot.create", "mcp.stop"]
    assert bot._mcp_runtime is None
    assert bot._nanobot_cog is None


async def test_nanobot_failure_does_not_stop_preowned_mcp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module, bot, recorder = bot_with_fakes(
        monkeypatch,
        tmp_path,
        create_fails=RuntimeError("nanobot construction failed"),
    )
    preowned_mcp = FakeMCPRuntime(
        settings=mcp_settings(enabled=True),
        music=FakeMusic(bot, recorder),
        recorder=recorder,
    )
    recorder.events.clear()
    bot._mcp_runtime = preowned_mcp

    with pytest.raises(RuntimeError, match="nanobot construction failed"):
        await bot.setup_hook()

    assert module is not None
    assert recorder.events == ["music", "nanobot.create"]
    assert bot._mcp_runtime is preowned_mcp
    assert bot._nanobot_cog is None


async def test_nanobot_cog_failure_closes_partial_client_and_mcp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _module, bot, recorder = bot_with_fakes(
        monkeypatch,
        tmp_path,
        cog_fails=RuntimeError("nanobot cog failed"),
    )

    with pytest.raises(RuntimeError, match="nanobot cog failed"):
        await bot.setup_hook()

    assert recorder.events == [
        "music",
        "mcp.start",
        "nanobot.create",
        "nanobot.cog",
        "client.close",
        "mcp.stop",
    ]
    assert bot._mcp_runtime is None
    assert bot._nanobot_cog is None


async def test_add_cog_failure_closes_cog_client_and_mcp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _module, bot, recorder = bot_with_fakes(
        monkeypatch,
        tmp_path,
        fail_nanobot_add=RuntimeError("add cog failed"),
    )

    with pytest.raises(RuntimeError, match="add cog failed"):
        await bot.setup_hook()

    assert recorder.events == [
        "music",
        "mcp.start",
        "nanobot.create",
        "add_cog",
        "nanobot.close",
        "client.close",
        "mcp.stop",
    ]
    assert bot._mcp_runtime is None
    assert bot._nanobot_cog is None


async def test_close_order_is_nanobot_mcp_discord_without_double_close(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _module, bot, recorder = bot_with_fakes(
        monkeypatch, tmp_path, record_discord_close=True
    )
    await bot.setup_hook()
    recorder.events.clear()

    await bot.close()
    await bot.close()

    assert recorder.events == [
        "nanobot.close",
        "client.close",
        "mcp.stop",
        "discord.close",
        "discord.close",
    ]
    assert bot._mcp_runtime is None
    assert bot._nanobot_cog is None


async def test_close_continues_cleanup_when_nanobot_close_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recorder = CompositionRecorder(
        nanobot_close_error=RuntimeError("nanobot close failed")
    )
    _module, bot, recorder = bot_with_fakes(
        monkeypatch,
        tmp_path,
        record_discord_close=True,
        recorder=recorder,
    )
    await bot.setup_hook()
    recorder.events.clear()

    with pytest.raises(RuntimeError, match="nanobot close failed"):
        await bot.close()

    assert recorder.events == ["nanobot.close", "mcp.stop", "discord.close"]
    assert bot._mcp_runtime is None
    assert bot._nanobot_cog is None


def test_commands_package_exports_nanobot_without_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_create() -> Never:
        raise AssertionError("SDK construction must not happen at import time")

    monkeypatch.setattr(
        "rosetta.utils.nanobot_client.NanobotSdkClient.create", fail_create
    )
    sys.modules.pop("rosetta.commands", None)

    commands_module = importlib.import_module("rosetta.commands")

    assert commands_module.Nanobot.__name__ == "Nanobot"
    assert "Nanobot" in commands_module.__all__
