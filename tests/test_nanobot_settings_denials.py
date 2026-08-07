from __future__ import annotations

import pytest

from rosetta.utils.nanobot_policy import GuildPolicy
from rosetta.utils.views.Nanobot import NanobotSettingsView
from tests.nanobot_settings_view_fakes import (
    CountingPolicyRepository,
    FakeInteraction,
    FakeOwnerCheck,
    FakePermissions,
    FakeUser,
    guild,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def opened_user_view(repository: CountingPolicyRepository) -> NanobotSettingsView:
    return NanobotSettingsView(
        policy_repository=repository,
        guild=guild(),
        user=FakeUser(id=99),
        policy=GuildPolicy(enabled=False, channel_ids=frozenset()),
    )


def owner_checked_view(repository: CountingPolicyRepository) -> NanobotSettingsView:
    return NanobotSettingsView(
        policy_repository=repository,
        guild=guild(),
        owner_check=FakeOwnerCheck(owner_id=99),
        policy=GuildPolicy(enabled=False, channel_ids=frozenset()),
    )


async def test_opened_user_view_denial_identifies_opening_administrator() -> None:
    # Given: administrator 99 opened the settings and administrator 100 tries the view.
    repository = CountingPolicyRepository()
    view = opened_user_view(repository)
    interaction = FakeInteraction(
        guild=guild(),
        user=FakeUser(id=100),
        permissions=FakePermissions(administrator=True),
    )

    # When: Discord runs the view-level interaction check.
    allowed = await view.interaction_check(interaction)

    # Then: the exact private denial names the opening-administrator authority.
    assert allowed is False
    assert interaction.response.sent[-1].content == (
        "Only the administrator who opened this Nanobot settings view can use it."
    )
    assert interaction.response.sent[-1].ephemeral is True
    assert repository.calls == 0


async def test_opened_user_mutation_denial_identifies_opening_administrator() -> None:
    # Given: a different administrator targets settings opened by administrator 99.
    repository = CountingPolicyRepository()
    view = opened_user_view(repository)
    interaction = FakeInteraction(
        guild=guild(),
        user=FakeUser(id=100),
        permissions=FakePermissions(administrator=True),
    )

    # When: the different administrator invokes a mutation callback.
    await view.enable(interaction)

    # Then: the exact denial describes mutation authority without reading policy.
    assert interaction.response.sent[-1].content == (
        "Only the administrator who opened this Nanobot settings view can change it."
    )
    assert interaction.response.sent[-1].ephemeral is True
    assert interaction.response.edits == []
    assert repository.calls == 0


async def test_explicit_owner_view_denial_retains_bot_owner_copy() -> None:
    # Given: explicit owner-check mode and a user who is not the bot owner.
    repository = CountingPolicyRepository()
    view = owner_checked_view(repository)
    interaction = FakeInteraction(
        guild=guild(),
        user=FakeUser(id=100),
        permissions=FakePermissions(administrator=True),
    )

    # When: Discord runs the view-level interaction check.
    allowed = await view.interaction_check(interaction)

    # Then: the exact private denial retains bot-owner use semantics.
    assert allowed is False
    assert interaction.response.sent[-1].content == (
        "Only the bot owner can use these Nanobot settings."
    )
    assert interaction.response.sent[-1].ephemeral is True
    assert repository.calls == 0


async def test_explicit_owner_mutation_denial_retains_bot_owner_copy() -> None:
    # Given: explicit owner-check mode and a non-owner without administrator permission.
    repository = CountingPolicyRepository()
    view = owner_checked_view(repository)
    interaction = FakeInteraction(
        guild=guild(),
        user=FakeUser(id=100),
        permissions=FakePermissions(administrator=False),
    )

    # When: the non-owner invokes a mutation callback.
    await view.enable(interaction)

    # Then: owner-check mode skips the opened-user admin gate and retains bot-owner copy.
    assert interaction.response.sent[-1].content == (
        "Only the bot owner can change Nanobot settings."
    )
    assert interaction.response.sent[-1].ephemeral is True
    assert interaction.response.edits == []
    assert repository.calls == 0
