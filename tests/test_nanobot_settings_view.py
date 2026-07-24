from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import discord
import pytest

from rosetta.commands.nanobot import Nanobot
from rosetta.utils.nanobot_policy import (
    ChannelId,
    GuildId,
    GuildPolicy,
    GuildPolicyRepository,
)
from rosetta.utils.views.Nanobot import NanobotSettingsView

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(slots=True)
class FakePermissions:
    administrator: bool


@dataclass(slots=True)
class FakeUser:
    id: int


@dataclass(frozen=True, slots=True)
class FakeChannel:
    id: int
    name: str
    type: discord.ChannelType


@dataclass(slots=True)
class FakeGuild:
    id: int
    channels: dict[int, FakeChannel]

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        return self.channels.get(channel_id)


@dataclass(frozen=True, slots=True)
class SentMessage:
    content: str | None
    ephemeral: bool
    view: discord.ui.View | None


@dataclass(slots=True)
class FakeResponse:
    sent: list[SentMessage] = field(default_factory=list)

    async def send_message(
        self,
        content: str | None = None,
        *,
        ephemeral: bool = False,
        view: discord.ui.View | None = None,
        allowed_mentions: discord.AllowedMentions | None = None,
    ) -> None:
        self.sent.append(SentMessage(content=content, ephemeral=ephemeral, view=view))

    async def edit_message(
        self,
        *,
        content: str | None = None,
        view: discord.ui.View | None = None,
        allowed_mentions: discord.AllowedMentions | None = None,
    ) -> None:
        return None


@dataclass(slots=True)
class FakeInteraction:
    guild: FakeGuild | None
    user: FakeUser
    permissions: FakePermissions
    response: FakeResponse = field(default_factory=FakeResponse)


class CountingPolicyRepository:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, guild_id: GuildId) -> GuildPolicy:
        self.calls += 1
        return GuildPolicy(enabled=False, channel_ids=frozenset())

    async def set_enabled(self, guild_id: GuildId, *, enabled: bool) -> None:
        self.calls += 1

    async def add_channel(self, guild_id: GuildId, channel_id: ChannelId) -> None:
        self.calls += 1

    async def remove_channel(self, guild_id: GuildId, channel_id: ChannelId) -> None:
        self.calls += 1


def policy_path(tmp_path: Path) -> Path:
    return tmp_path / "guild-policies.json"


def guild(*channels: FakeChannel) -> FakeGuild:
    return FakeGuild(id=10, channels={channel.id: channel for channel in channels})


def admin_interaction(server: FakeGuild | None) -> FakeInteraction:
    return FakeInteraction(server, FakeUser(id=99), FakePermissions(administrator=True))


def non_admin_interaction(server: FakeGuild | None) -> FakeInteraction:
    return FakeInteraction(
        server, FakeUser(id=13), FakePermissions(administrator=False)
    )


def view_text(view: NanobotSettingsView) -> str:
    return view.render_text()


def custom_ids(view: NanobotSettingsView) -> set[str]:
    return {item.custom_id for item in view.children if item.custom_id is not None}


def channel_selects(view: NanobotSettingsView) -> list[discord.ui.ChannelSelect]:
    return [
        item for item in view.children if isinstance(item, discord.ui.ChannelSelect)
    ]


async def open_settings(
    repository: GuildPolicyRepository,
    server: FakeGuild,
) -> NanobotSettingsView:
    cog = Nanobot(bot=None, policy_repository=repository)
    interaction = admin_interaction(server)

    await cog.settings.callback(cog, interaction)

    sent = interaction.response.sent[-1]
    assert sent.ephemeral is True
    assert isinstance(sent.view, NanobotSettingsView)
    return sent.view


async def test_command_is_guild_install_guild_context_and_administrator_default() -> (
    None
):
    # Given: the Nanobot command group and settings view are constructed.
    group = Nanobot.nanobot_group
    view = NanobotSettingsView(
        policy_repository=CountingPolicyRepository(),
        guild=guild(),
        user=FakeUser(id=99),
        policy=GuildPolicy(enabled=False, channel_ids=frozenset()),
    )

    # When / Then: Discord receives guild-only admin metadata and text-only batch controls.
    assert group.allowed_installs.guild is True
    assert group.allowed_installs.user is False
    assert group.allowed_contexts.guild is True
    assert group.allowed_contexts.dm_channel is False
    assert group.allowed_contexts.private_channel is False
    assert group.default_permissions == discord.Permissions(administrator=True)
    selects = channel_selects(view)
    assert len(selects) == 2
    assert {select.custom_id for select in selects} == {
        "nanobot_add_channels",
        "nanobot_remove_channels",
    }
    assert all(select.max_values == 25 for select in selects)
    assert all(select.channel_types == [discord.ChannelType.text] for select in selects)
    assert {"nanobot_enable", "nanobot_disable"}.issubset(custom_ids(view))


@pytest.mark.parametrize(
    "interaction", [non_admin_interaction(guild()), admin_interaction(None)]
)
async def test_command_denies_before_repository_read_when_not_admin_or_not_guild(
    interaction: FakeInteraction,
) -> None:
    # Given: a command invocation that is not both guild-scoped and administrator-authorized.
    repository = CountingPolicyRepository()
    cog = Nanobot(bot=None, policy_repository=repository)

    # When: the settings command runs.
    await cog.settings.callback(cog, interaction)

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

    # When: admin enables, adds 20/30, reopens, removes 20, and non-admins try command/callback.
    view = await open_settings(repository, server)
    await view.enable(admin_interaction(server))
    await view.add_channels(admin_interaction(server), tuple(server.channels.values()))
    reopened = await open_settings(repository, server)
    await reopened.remove_channels(admin_interaction(server), (server.channels[20],))

    blocked_repository = CountingPolicyRepository()
    blocked_cog = Nanobot(bot=None, policy_repository=blocked_repository)
    blocked_command = non_admin_interaction(server)
    await blocked_cog.settings.callback(blocked_cog, blocked_command)
    blocked_view = NanobotSettingsView(
        policy_repository=blocked_repository,
        guild=server,
        user=FakeUser(id=13),
        policy=GuildPolicy(enabled=False, channel_ids=frozenset()),
    )
    blocked_callback = non_admin_interaction(server)
    await blocked_view.enable(blocked_callback)

    # Then: the final surface shows only channel 30 and prints manual QA checks.
    ephemeral = blocked_command.response.sent[-1].ephemeral
    invoker_check = await blocked_view.interaction_check(blocked_callback)
    print(f"ephemeral={ephemeral}")
    print(f"invoker_check={invoker_check}")
    print(f"state={view_text(reopened)}")
    print(f"non_admin_repository_calls={blocked_repository.calls}")
    assert "ops" in view_text(reopened)
    assert "general" not in view_text(reopened)
    assert ephemeral is True
    assert invoker_check is True
    assert blocked_repository.calls == 0
