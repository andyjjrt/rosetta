from __future__ import annotations

from dataclasses import dataclass, field

import discord

from rosetta.utils.nanobot_policy import ChannelId, GuildId, GuildPolicy
from rosetta.utils.views.Nanobot import NanobotSettingsView


@dataclass(frozen=True, slots=True)
class FakePermissions:
    administrator: bool


@dataclass(frozen=True, slots=True)
class FakeUser:
    id: int


@dataclass(frozen=True, slots=True)
class FakeChannel:
    id: int
    name: str
    type: discord.ChannelType


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class EditedMessage:
    content: str | None
    view: discord.ui.LayoutView | None
    allowed_mentions: discord.AllowedMentions | None


@dataclass(frozen=True, slots=True)
class FakeResponse:
    sent: list[SentMessage] = field(default_factory=list)
    edits: list[EditedMessage] = field(default_factory=list)

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
        view: discord.ui.LayoutView | None = None,
        allowed_mentions: discord.AllowedMentions | None = None,
    ) -> None:
        self.edits.append(
            EditedMessage(
                content=content,
                view=view,
                allowed_mentions=allowed_mentions,
            )
        )


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class FakeOwnerCheck:
    owner_id: int

    async def is_owner(self, user: FakeUser) -> bool:
        return user.id == self.owner_id


def guild(*channels: FakeChannel) -> FakeGuild:
    return FakeGuild(id=10, channels={channel.id: channel for channel in channels})


def admin_interaction(server: FakeGuild | None) -> FakeInteraction:
    return FakeInteraction(server, FakeUser(id=99), FakePermissions(administrator=True))


def non_admin_interaction(server: FakeGuild | None) -> FakeInteraction:
    return FakeInteraction(
        server, FakeUser(id=13), FakePermissions(administrator=False)
    )


def view_text(view: NanobotSettingsView) -> str:
    return "\n".join(
        item.content
        for item in view.walk_children()
        if isinstance(item, discord.ui.TextDisplay)
    )


def custom_ids(view: NanobotSettingsView) -> set[str]:
    return {
        item.custom_id
        for item in view.walk_children()
        if isinstance(item, discord.ui.Button | discord.ui.ChannelSelect)
        and item.custom_id is not None
    }


def channel_selects(view: NanobotSettingsView) -> list[discord.ui.ChannelSelect]:
    return [
        item
        for item in view.walk_children()
        if isinstance(item, discord.ui.ChannelSelect)
    ]


def button(view: NanobotSettingsView, custom_id: str) -> discord.ui.Button:
    return next(
        item
        for item in view.walk_children()
        if isinstance(item, discord.ui.Button) and item.custom_id == custom_id
    )
