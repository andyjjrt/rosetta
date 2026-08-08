from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rosetta.utils.config import MCPConfig, McpSetting


@pytest.fixture(autouse=True)
def clear_mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.startswith(("MCP_", "SETTING_")):
            monkeypatch.delenv(key, raising=False)


def fresh_settings() -> McpSetting:
    return McpSetting(_env_file=None)


def test_disabled_defaults_load_without_secret() -> None:
    settings = fresh_settings()

    assert settings.ENABLED is False
    assert settings.BEARER_TOKEN is None
    assert isinstance(MCPConfig, McpSetting)
    settings.validate_startup()


def test_setting_database_path_defaults_to_local_sqlite() -> None:
    # Given: no settings database path override is present.
    import rosetta.utils.config as config

    # When: the settings config object is read without a real .env file.
    settings = config.SettingSetting(_env_file=None)

    # Then: runtime state defaults to the local settings SQLite database.
    assert settings.DATABASE_PATH == Path(".data/settings.sqlite3")
    assert isinstance(config.SettingConfig, config.SettingSetting)


def test_setting_database_path_reads_setting_env_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: the operator supplies SETTING_DATABASE_PATH.
    import rosetta.utils.config as config

    database_path = tmp_path / "settings.sqlite3"
    monkeypatch.setenv("SETTING_DATABASE_PATH", str(database_path))

    # When: settings are loaded from environment variables only.
    settings = config.SettingSetting(_env_file=None)

    # Then: the SETTING_ prefix drives the database path value.
    assert settings.DATABASE_PATH == database_path


def test_enabled_secret_stays_redacted_in_repr_and_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "a" * 32)

    settings = fresh_settings()

    assert isinstance(settings.BEARER_TOKEN, SecretStr)
    assert "a" * 32 not in repr(settings)
    assert "a" * 32 not in settings.model_dump_json()
    settings.validate_startup()


def test_enabled_mcp_accepts_missing_bearer_token() -> None:
    # Given: MCP is explicitly enabled without an operator bearer token.
    settings = McpSetting(
        ENABLED=True,
        PATH="/mcp",
        BEARER_TOKEN=None,
        ALLOWED_HOSTS=["127.0.0.1"],
        _env_file=None,
    )

    # When / Then: startup validation accepts a missing bearer token.
    settings.validate_startup()


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (McpSetting(ENABLED=True, PATH="mcp", _env_file=None), "PATH"),
        (
            McpSetting(ENABLED=True, ALLOWED_HOSTS=[], _env_file=None),
            "ALLOWED_HOSTS",
        ),
    ],
)
def test_enabled_mcp_without_bearer_still_validates_startup_configuration(
    settings: McpSetting,
    message: str,
) -> None:
    # Given: MCP is enabled without a bearer token and has invalid startup config.
    # When / Then: non-auth startup invariants are still enforced.
    with pytest.raises(ValueError, match=message):
        settings.validate_startup()


@pytest.mark.parametrize(
    ("env", "message"),
    [
        (
            {"MCP_ENABLED": "true", "MCP_BEARER_TOKEN": "a" * 32, "MCP_PATH": "mcp"},
            "PATH",
        ),
        (
            {"MCP_ENABLED": "true", "MCP_BEARER_TOKEN": "a" * 32, "MCP_PATH": "//mcp"},
            "PATH",
        ),
        (
            {
                "MCP_ENABLED": "true",
                "MCP_BEARER_TOKEN": "a" * 32,
                "MCP_ALLOWED_HOSTS": "[]",
            },
            "ALLOWED_HOSTS",
        ),
        (
            {
                "MCP_ENABLED": "true",
                "MCP_BEARER_TOKEN": "a" * 32,
                "MCP_ALLOWED_HOSTS": '["*.example.com"]',
            },
            "MCP SDK does not support wildcard host patterns",
        ),
    ],
)
def test_startup_validation_rejects_invalid_configuration(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    message: str,
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    settings = fresh_settings()

    with pytest.raises(ValueError, match=message):
        settings.validate_startup()
