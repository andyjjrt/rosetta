from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rosetta.utils.config import CogSetting


@pytest.fixture(autouse=True)
def clear_nanobot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.startswith(("COG_", "NANOBOT_")):
            monkeypatch.delenv(key, raising=False)


def fresh_cog_settings() -> CogSetting:
    return CogSetting(_env_file=None)


def nanobot_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-secret-value")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "openai/test-model")
    monkeypatch.setenv("NANOBOT_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MCP_PORT", "8000")
    monkeypatch.setenv("MCP_PATH", "/mcp")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "b" * 32)


def test_existing_cog_defaults_remain_enabled() -> None:
    # Given: no cog environment overrides are present.
    settings = fresh_cog_settings()

    # When: existing cog disable flags are read from defaults.
    existing_disable_flags = (
        settings.BASICS_DISABLE,
        settings.MUSIC_DISABLE,
        settings.MYGO_DISABLE,
        settings.LLM_DISABLE,
    )

    # Then: existing cogs remain enabled by default.
    assert existing_disable_flags == (False, False, False, False)


def test_nanobot_defaults_are_opt_in() -> None:
    # Given: no Nanobot environment overrides are present.
    from rosetta.utils.config import NanobotSetting

    cog_settings = fresh_cog_settings()
    nanobot_settings = NanobotSetting(_env_file=None)

    # When: startup validation is evaluated while the cog remains disabled.
    nanobot_settings.validate_startup(cog_settings)

    # Then: no config file is required until the operator opts in.
    assert cog_settings.NANOBOT_DISABLE is True
    assert nanobot_settings.CONFIG_PATH == Path(".data/nanobot/config.json")
    assert nanobot_settings.POLICY_PATH == Path(".data/nanobot/guild-policies.json")
    assert nanobot_settings.MAX_CONCURRENT_RUNS == 3


def test_nanobot_opt_in_requires_readable_config_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: the Nanobot cog is enabled with a missing config path.
    from rosetta.utils.config import NanobotConfigError, NanobotSetting

    missing_config = tmp_path / "missing-nanobot.json"
    monkeypatch.setenv("COG_NANOBOT_DISABLE", "false")
    monkeypatch.setenv("NANOBOT_CONFIG_PATH", str(missing_config))
    monkeypatch.setenv("NANOBOT_POLICY_PATH", str(tmp_path / "guild-policies.json"))

    cog_settings = fresh_cog_settings()
    nanobot_settings = NanobotSetting(_env_file=None)

    # When: startup validation checks the operator-owned file path.
    with pytest.raises(NanobotConfigError) as error_info:
        nanobot_settings.validate_startup(cog_settings)

    # Then: the failure is actionable and contains no unrelated secret values.
    message = str(error_info.value)
    assert "NANOBOT_CONFIG_PATH" in message
    assert str(missing_config) in message
    assert "LLM_API_KEY" not in message


def test_nanobot_accepts_existing_config_without_parsing_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: the Nanobot cog is enabled and the operator config file is readable.
    from rosetta.utils.config import NanobotSetting

    config_path = tmp_path / "nanobot.config.json"
    config_path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("COG_NANOBOT_DISABLE", "false")
    monkeypatch.setenv("NANOBOT_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("NANOBOT_POLICY_PATH", str(tmp_path / "guild-policies.json"))

    cog_settings = fresh_cog_settings()
    nanobot_settings = NanobotSetting(_env_file=None)

    # When: Rosetta validates only ownership/readability of the path.
    nanobot_settings.validate_startup(cog_settings)

    # Then: runtime did not parse or rewrite the Nanobot JSON file.
    assert config_path.read_text(encoding="utf-8") == "{not-json"


def test_nanobot_rejects_zero_concurrent_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an invalid concurrency limit is supplied at the env boundary.
    from rosetta.utils.config import NanobotSetting

    monkeypatch.setenv("NANOBOT_MAX_CONCURRENT_RUNS", "0")

    # When / Then: Pydantic rejects it before runtime startup.
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        NanobotSetting(_env_file=None)


@pytest.mark.anyio
async def test_example_config_loads_through_public_nanobot_sdk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: placeholder deployment env values for the committed example config.
    from nanobot import Nanobot

    nanobot_env(monkeypatch, tmp_path)

    config_path = Path("nanobot.config.example.json")

    # When: Nanobot 0.2.2 loads the config through its public SDK facade.
    async with Nanobot.from_config(config_path=config_path) as bot:
        runtime_model = bot.runtime.model
        runtime_workspace = bot.runtime.workspace

    example = json.loads(config_path.read_text(encoding="utf-8"))

    # Then: key operator-owned safety and Rosetta MCP fields survive parsing.
    assert runtime_model == "openai/test-model"
    assert runtime_workspace == tmp_path / "workspace"
    assert example["agents"]["defaults"]["modelPreset"] == "rosetta"
    assert example["agents"]["defaults"]["timezone"] == "Asia/Taipei"
    assert example["agents"]["defaults"]["unifiedSession"] is False
    assert example["agents"]["defaults"]["dream"]["enabled"] is False
    assert example["transcription"]["enabled"] is False
    assert example["tools"]["restrictToWorkspace"] is True
    assert example["tools"]["file"]["enable"] is True
    assert example["tools"]["exec"]["enable"] is False
    assert example["tools"]["web"]["enable"] is False
    assert example["tools"]["ssrfWhitelist"] == ["127.0.0.1/32"]
    assert example["tools"]["mcpServers"]["rosetta"]["enabledTools"] == [
        "search",
        "play",
    ]
