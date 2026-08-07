from __future__ import annotations

import logging
from dataclasses import dataclass, field

import discord
import pytest

from rosetta.utils.cog import Cog
from rosetta.utils.log import LogContext

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True, slots=True)
class FakeUser:
    id: int

    def __str__(self) -> str:
        return "operator"


@dataclass(frozen=True, slots=True)
class FakeCommand:
    name: str = "list"
    qualified_name: str = "setting llm list"


@dataclass(frozen=True, slots=True)
class FakeInteraction:
    type: discord.InteractionType = discord.InteractionType.application_command
    command: FakeCommand = field(default_factory=FakeCommand)
    user: FakeUser = field(default_factory=lambda: FakeUser(id=123))
    guild: None = None
    channel: None = None
    data: None = None
    extras: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FakeBot:
    pass


async def test_nested_application_command_logs_full_qualified_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: Discord resolves a command nested under two application-command groups.
    interaction = FakeInteraction()
    cog = Cog(FakeBot())
    caplog.set_level(logging.INFO, logger="rosetta")

    # When: the shared interaction setup records command invocation context.
    accepted = await cog.interaction_setup(interaction)

    # Then: both the log message and structured context contain the complete slash path.
    assert accepted is True
    assert "Command '/setting llm list' invoked" in caplog.text
    assert LogContext.from_interaction(interaction).command == "/setting llm list"
