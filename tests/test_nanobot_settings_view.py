from __future__ import annotations

from pathlib import Path

import discord
import pytest

from rosetta.utils.nanobot_policy import (
    ChannelId,
    GuildId,
    GuildPolicy,
    GuildPolicyRepository,
)
from rosetta.utils.views.Nanobot import NanobotSettingsView
from tests.nanobot_settings_view_fakes import (
    CountingPolicyRepository,
    FakeChannel,
    FakeGuild,
    FakeInteraction,
    FakePermissions,
    FakeUser,
    admin_interaction,
    button,
    channel_selects,
    custom_ids,
    guild,
    non_admin_interaction,
    view_text,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def policy_path(tmp_path: Path) -> Path:
    return tmp_path / "guild-policies.json"


async def open_settings(
    repository: GuildPolicyRepository,
    server: FakeGuild,
) -> NanobotSettingsView:
    policy = await repository.get(GuildId(str(server.id)))
    return NanobotSettingsView(
        policy_repository=repository,
        guild=server,
        user=FakeUser(id=99),
        policy=policy,
    )


async def test_view_uses_text_only_batch_controls() -> None:
    # Given: a Nanobot settings view is constructed.
    view = NanobotSettingsView(
        policy_repository=CountingPolicyRepository(),
        guild=guild(),
        user=FakeUser(id=99),
        policy=GuildPolicy(enabled=False, channel_ids=frozenset()),
    )

    # When / Then: Discord receives one Components v2 container with nested controls.
    assert isinstance(view, discord.ui.LayoutView)
    assert len(view.children) == 1
    assert isinstance(view.children[0], discord.ui.Container)
    selects = channel_selects(view)
    assert len(selects) == 2
    assert {select.custom_id for select in selects} == {
        "nanobot_add_channels",
        "nanobot_remove_channels",
    }
    assert all(select.max_values == 25 for select in selects)
    assert all(select.channel_types == [discord.ChannelType.text] for select in selects)
    assert {"nanobot_enable", "nanobot_disable"}.issubset(custom_ids(view))


async def test_view_renders_status_empty_warning_and_contentless_refresh(
    tmp_path: Path,
) -> None:
    # Given: a disabled empty policy displayed in a Components v2 view.
    repository = GuildPolicyRepository(policy_path(tmp_path))
    server = guild()
    view = await open_settings(repository, server)
    interaction = admin_interaction(server)
    assert "Nanobot settings" in view_text(view)
    assert "Status: **Disabled**" in view_text(view)
    assert "Allowed channels: none" in view_text(view)
    assert "Page 1/1" in view_text(view)

    # When: the administrator enables the empty policy.
    await view.enable(interaction)

    # Then: status, warning, controls, and the contentless mention-safe edit refresh.
    assert "Status: **Enabled**" in view_text(view)
    assert "mentions will not be handled" in view_text(view)
    assert button(view, "nanobot_enable").disabled is True
    assert button(view, "nanobot_disable").disabled is False
    edit = interaction.response.edits[-1]
    assert edit.content is None
    assert edit.view is view
    assert edit.allowed_mentions is not None
    assert edit.allowed_mentions.to_dict() == {"parse": []}


async def test_allowed_channels_paginate_five_at_a_time_and_recheck_access(
    tmp_path: Path,
) -> None:
    # Given: seven allowed channels including escaped display data and one missing channel.
    repository = GuildPolicyRepository(policy_path(tmp_path))
    channels = tuple(
        FakeChannel(
            id=channel_id,
            name=(
                "team_*ops*@everyone" if channel_id == 20 else f"channel-{channel_id}"
            ),
            type=discord.ChannelType.text,
        )
        for channel_id in range(20, 26)
    )
    server = guild(*channels)
    await repository.set_enabled(GuildId("10"), enabled=True)
    for channel_id in range(20, 27):
        await repository.add_channel(GuildId("10"), ChannelId(str(channel_id)))
    view = await open_settings(repository, server)

    # When / Then: page one contains five escaped rows and deterministic page controls.
    first_page = view_text(view)
    assert "team\\_\\*ops\\*@everyone" not in first_page
    assert "team\\_\\*ops\\*@\u200beveryone" in first_page
    assert "channel-24" in first_page
    assert "channel-25" not in first_page
    assert "Page 1/2" in first_page
    assert {"nanobot_previous", "nanobot_next"}.issubset(custom_ids(view))
    assert button(view, "nanobot_previous").disabled is True
    assert button(view, "nanobot_next").disabled is False

    # When: the opening administrator moves to the next page.
    page_interaction = admin_interaction(server)
    await view.go_next(page_interaction)

    # Then: the remaining real and fallback channels render with stable bounds.
    second_page = view_text(view)
    assert "channel-25" in second_page
    assert "channel `26`" in second_page
    assert "Page 2/2" in second_page
    assert button(view, "nanobot_previous").disabled is False
    assert button(view, "nanobot_next").disabled is True

    # When: a non-owner administrator attempts to page.
    intruder = FakeInteraction(
        guild=server,
        user=FakeUser(id=100),
        permissions=FakePermissions(administrator=True),
    )
    await view.go_previous(intruder)

    # Then: authorization is rechecked and neither page nor message changes.
    assert view_text(view) == second_page
    assert intruder.response.edits == []
    assert intruder.response.sent[-1].ephemeral is True


@pytest.mark.parametrize(
    "interaction", [non_admin_interaction(guild()), admin_interaction(None)]
)
async def test_view_callback_denies_before_repository_read_when_not_admin_or_not_guild(
    interaction: FakeInteraction,
) -> None:
    # Given: a callback invocation that is not both guild-scoped and administrator-authorized.
    repository = CountingPolicyRepository()
    view = NanobotSettingsView(
        policy_repository=repository,
        guild=guild(),
        user=interaction.user,
        policy=GuildPolicy(enabled=False, channel_ids=frozenset()),
    )

    # When: the settings callback runs.
    await view.enable(interaction)

    # Then: the response is ephemeral and the repository is never touched.
    assert repository.calls == 0
    assert interaction.response.sent[-1].ephemeral is True


async def test_view_is_invoker_only_and_blocks_repository_access() -> None:
    # Given: a settings view opened by one administrator.
    repository = CountingPolicyRepository()
    server = guild()
    view = NanobotSettingsView(
        policy_repository=repository,
        guild=server,
        user=FakeUser(id=99),
        policy=GuildPolicy(enabled=False, channel_ids=frozenset()),
    )
    intruder = FakeInteraction(
        guild=server,
        user=FakeUser(id=100),
        permissions=FakePermissions(administrator=True),
    )

    # When: another administrator tries to use the view.
    allowed = await view.interaction_check(intruder)

    # Then: the view denies the interaction before any policy access.
    assert allowed is False
    assert repository.calls == 0
    assert intruder.response.sent[-1].ephemeral is True


async def test_enable_with_zero_channels_persists_and_warns_mentions_are_idle(
    tmp_path: Path,
) -> None:
    # Given: a disabled guild with no allowed channels.
    repository = GuildPolicyRepository(policy_path(tmp_path))
    server = guild()
    view = await open_settings(repository, server)
    assert "Disabled" in view_text(view)

    # When: the administrator enables Nanobot without adding channels.
    await view.enable(admin_interaction(server))

    # Then: the policy is enabled and the UI explicitly says mentions stay unhandled.
    policy = await repository.get(GuildId("10"))
    assert policy.enabled is True
    assert policy.channel_ids == frozenset()
    assert "Enabled" in view_text(view)
    assert "mentions will not be handled" in view_text(view)


async def test_add_and_remove_text_channels_are_repeatable_idempotent_batches(
    tmp_path: Path,
) -> None:
    # Given: an enabled guild and three selected channels, one of which is not text.
    repository = GuildPolicyRepository(policy_path(tmp_path))
    server = guild(
        FakeChannel(id=20, name="general", type=discord.ChannelType.text),
        FakeChannel(id=30, name="team_*ops*", type=discord.ChannelType.text),
        FakeChannel(id=40, name="voice", type=discord.ChannelType.voice),
    )
    view = await open_settings(repository, server)
    await view.enable(admin_interaction(server))

    # When: channels are added and removed in repeated batches.
    await view.add_channels(admin_interaction(server), tuple(server.channels.values()))
    await view.add_channels(admin_interaction(server), tuple(server.channels.values()))
    await view.remove_channels(
        admin_interaction(server),
        (server.channels[20], server.channels[20], server.channels[40]),
    )

    # Then: only text channels mutate policy, duplicates are harmless, and names are display data.
    policy = await repository.get(GuildId("10"))
    assert policy.channel_ids == frozenset({ChannelId("30")})
    assert "team\\_\\*ops\\*" in view_text(view)
    assert ChannelId("40") not in policy.channel_ids


async def test_callbacks_reread_stale_state_before_mutating_and_refresh(
    tmp_path: Path,
) -> None:
    # Given: an open stale disabled view while another actor has enabled channel 30.
    repository = GuildPolicyRepository(policy_path(tmp_path))
    server = guild(FakeChannel(id=30, name="ops", type=discord.ChannelType.text))
    view = await open_settings(repository, server)
    await repository.set_enabled(GuildId("10"), enabled=True)
    await repository.add_channel(GuildId("10"), ChannelId("30"))

    # When: the stale view toggles disable.
    await view.disable(admin_interaction(server))

    # Then: the callback preserved the externally-added channel and refreshed the displayed state.
    policy = await repository.get(GuildId("10"))
    assert policy.enabled is False
    assert policy.channel_ids == frozenset({ChannelId("30")})
    assert "Disabled" in view_text(view)
    assert "ops" in view_text(view)


async def test_manual_qa_admin_sequence_reopen_and_non_admin_zero_calls(
    tmp_path: Path,
) -> None:
    # Given: the requested executable fake interaction sequence.
    repository = GuildPolicyRepository(policy_path(tmp_path))
    server = guild(
        FakeChannel(id=20, name="general", type=discord.ChannelType.text),
        FakeChannel(id=30, name="ops", type=discord.ChannelType.text),
    )

    # When: admin enables, adds 20/30, reopens, removes 20, and a non-admin tries a callback.
    view = await open_settings(repository, server)
    await view.enable(admin_interaction(server))
    await view.add_channels(admin_interaction(server), tuple(server.channels.values()))
    reopened = await open_settings(repository, server)
    await reopened.remove_channels(admin_interaction(server), (server.channels[20],))

    blocked_repository = CountingPolicyRepository()
    blocked_view = NanobotSettingsView(
        policy_repository=blocked_repository,
        guild=server,
        user=FakeUser(id=13),
        policy=GuildPolicy(enabled=False, channel_ids=frozenset()),
    )
    blocked_callback = non_admin_interaction(server)
    await blocked_view.enable(blocked_callback)

    # Then: the final surface shows only channel 30 and prints manual QA checks.
    invoker_check = await blocked_view.interaction_check(blocked_callback)
    print(f"ephemeral={blocked_callback.response.sent[-1].ephemeral}")
    print(f"invoker_check={invoker_check}")
    print(f"state={view_text(reopened)}")
    print(f"non_admin_repository_calls={blocked_repository.calls}")
    assert "ops" in view_text(reopened)
    assert "general" not in view_text(reopened)
    assert blocked_callback.response.sent[-1].ephemeral is True
    assert invoker_check is True
    assert blocked_repository.calls == 0
