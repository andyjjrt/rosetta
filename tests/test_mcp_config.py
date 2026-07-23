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
        if key.startswith("MCP_"):
            monkeypatch.delenv(key, raising=False)


def fresh_settings() -> McpSetting:
    return McpSetting(_env_file=None)


def test_disabled_defaults_load_without_secret() -> None:
    settings = fresh_settings()

    assert settings.ENABLED is False
    assert settings.BEARER_TOKEN is None
    assert isinstance(MCPConfig, McpSetting)
    settings.validate_startup()


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


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"MCP_ENABLED": "true"}, "MCP_BEARER_TOKEN"),
        ({"MCP_ENABLED": "true", "MCP_BEARER_TOKEN": "short-secret"}, "at least 32"),
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
