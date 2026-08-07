from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import rosetta.commands.llm as llm_module
from rosetta.commands.llm import LLM
from rosetta.utils.llm_model_access import LlmModelAccessRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True, slots=True)
class FakeUser:
    id: int


@dataclass(frozen=True, slots=True)
class FakeBot:
    owner_id: int

    async def is_owner(self, user: FakeUser) -> bool:
        return user.id == self.owner_id


@dataclass(frozen=True, slots=True)
class FakeInteraction:
    user: FakeUser
    client: FakeBot


@dataclass(frozen=True, slots=True)
class FakeModel:
    id: str


@dataclass(frozen=True, slots=True)
class FakeModelPage:
    data: list[FakeModel]


class FakeModelsClient:
    async def list(self) -> FakeModelPage:
        return FakeModelPage(data=[FakeModel("alpha"), FakeModel("beta")])


@dataclass(frozen=True, slots=True)
class FakeOpenAIClient:
    models: FakeModelsClient


async def test_allowlisted_user_gets_full_model_autocomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: a non-owner is in the persisted model-selection allowlist.
    repository = LlmModelAccessRepository(tmp_path / "settings.sqlite3")
    await repository.add(2)
    bot = FakeBot(owner_id=1)
    cog = LLM(bot, model_access_repository=repository)
    interaction = FakeInteraction(user=FakeUser(2), client=bot)
    monkeypatch.setattr(
        llm_module,
        "client",
        FakeOpenAIClient(models=FakeModelsClient()),
    )

    # When: Discord requests model autocomplete choices.
    choices = await cog.model_autocomplete(interaction, "a")

    # Then: the allowlisted user receives provider model choices.
    assert [(choice.name, choice.value) for choice in choices] == [
        ("alpha", "alpha"),
        ("beta", "beta"),
    ]
    assert await cog.can_select_model(interaction) is True


async def test_unlisted_user_remains_limited_to_default_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: a non-owner is absent from the model-selection allowlist.
    repository = LlmModelAccessRepository(tmp_path / "settings.sqlite3")
    bot = FakeBot(owner_id=1)
    cog = LLM(bot, model_access_repository=repository)
    interaction = FakeInteraction(user=FakeUser(2), client=bot)
    monkeypatch.setattr(llm_module.LLMConfig, "DEFAULT_MODEL", "alpha")

    # When: Discord requests model autocomplete choices.
    choices = await cog.model_autocomplete(interaction, "a")

    # Then: only the configured default remains visible and selectable.
    assert [(choice.name, choice.value) for choice in choices] == [("alpha", "alpha")]
    assert await cog.can_select_model(interaction) is False


async def test_owner_can_select_models_without_allowlist_entry(tmp_path: Path) -> None:
    # Given: the bot owner is absent from the model-selection allowlist.
    repository = LlmModelAccessRepository(tmp_path / "settings.sqlite3")
    bot = FakeBot(owner_id=1)
    cog = LLM(bot, model_access_repository=repository)
    interaction = FakeInteraction(user=FakeUser(1), client=bot)

    # When / Then: owner status independently authorizes model selection.
    assert await cog.can_select_model(interaction) is True
