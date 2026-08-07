from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final, Protocol

import discord

from rosetta.utils.nanobot_policy import ChannelId, GuildId, GuildPolicy

_BATCH_LIMIT: Final = 25
_ACCENT_COLOR: Final = 0x229AE0
_PAGE_SIZE: Final = 5


class NanobotPolicyStore(Protocol):
    async def get(self, guild_id: GuildId) -> GuildPolicy: ...

    async def set_enabled(self, guild_id: GuildId, *, enabled: bool) -> None: ...

    async def add_channel(self, guild_id: GuildId, channel_id: ChannelId) -> None: ...

    async def remove_channel(
        self, guild_id: GuildId, channel_id: ChannelId
    ) -> None: ...


class SettingsGuild(Protocol):
    id: int

    def get_channel(self, channel_id: int) -> SettingsChannel | None: ...


class SettingsChannel(Protocol):
    id: int
    name: str
    type: discord.ChannelType


class SettingsUser(Protocol):
    id: int


class NanobotOwnerCheck(Protocol):
    async def is_owner(self, user: SettingsUser) -> bool: ...


class _OpenedUserOwnerCheck:
    def __init__(self, user: SettingsUser) -> None:
        self._user_id = user.id

    async def is_owner(self, user: SettingsUser) -> bool:
        return user.id == self._user_id


class NanobotSettingsView(discord.ui.LayoutView):
    def __init__(
        self,
        *,
        policy_repository: NanobotPolicyStore,
        guild: SettingsGuild,
        policy: GuildPolicy,
        owner_check: NanobotOwnerCheck | None = None,
        user: SettingsUser | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self._policy_repository = policy_repository
        self._guild = guild
        self._guild_id = GuildId(str(guild.id))
        self._owner_check = owner_check or _OpenedUserOwnerCheck(user)
        self._requires_administrator = owner_check is None
        self._policy = policy
        self._page = 1
        self._refresh_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await self._owner_check.is_owner(interaction.user):
            return True

        await self._send_denial(interaction, self._authority_denial(changing=False))
        return False

    def render_text(self) -> str:
        status = "Enabled" if self._policy.enabled else "Disabled"
        channels = self._format_allowed_channels()
        text = (
            f"**Nanobot settings**\nStatus: **{status}**\nAllowed channels: {channels}"
        )
        if self._policy.enabled and not self._policy.channel_ids:
            text += "\nNanobot is enabled, but mentions will not be handled until at least one text channel is allowed."
        return text

    async def enable(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_callback_allowed(interaction):
            return

        self._policy = await self._policy_repository.get(self._guild_id)
        await self._policy_repository.set_enabled(self._guild_id, enabled=True)
        await self._refresh_message(interaction)

    async def disable(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_callback_allowed(interaction):
            return

        self._policy = await self._policy_repository.get(self._guild_id)
        await self._policy_repository.set_enabled(self._guild_id, enabled=False)
        await self._refresh_message(interaction)

    async def add_channels(
        self,
        interaction: discord.Interaction,
        channels: Sequence[SettingsChannel],
    ) -> None:
        if not await self._ensure_callback_allowed(interaction):
            return

        self._policy = await self._policy_repository.get(self._guild_id)
        for channel_id in self._text_channel_ids(channels):
            await self._policy_repository.add_channel(self._guild_id, channel_id)
        await self._refresh_message(interaction)

    async def remove_channels(
        self,
        interaction: discord.Interaction,
        channels: Sequence[SettingsChannel],
    ) -> None:
        if not await self._ensure_callback_allowed(interaction):
            return

        self._policy = await self._policy_repository.get(self._guild_id)
        for channel_id in self._text_channel_ids(channels):
            await self._policy_repository.remove_channel(self._guild_id, channel_id)
        await self._refresh_message(interaction)

    async def go_previous(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_callback_allowed(interaction):
            return
        await self._refresh_message(interaction, page_delta=-1)

    async def go_next(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_callback_allowed(interaction):
            return
        await self._refresh_message(interaction, page_delta=1)

    def _refresh_items(self) -> None:
        self.clear_items()
        status = "Enabled" if self._policy.enabled else "Disabled"
        container = discord.ui.Container(
            discord.ui.TextDisplay("**Nanobot settings**"),
            discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small),
            discord.ui.TextDisplay(f"Status: **{status}**"),
            accent_color=_ACCENT_COLOR,
        )
        channel_ids = self._page_channel_ids()
        if channel_ids:
            container.add_item(discord.ui.TextDisplay("**Allowed channels**"))
            start = (self._page - 1) * _PAGE_SIZE
            for index, channel_id in enumerate(channel_ids, start=start + 1):
                text = f"{index}. {self._format_channel(channel_id)}"
                container.add_item(discord.ui.TextDisplay(text))
        else:
            container.add_item(discord.ui.TextDisplay("Allowed channels: none"))
        if self._policy.enabled and not self._policy.channel_ids:
            container.add_item(
                discord.ui.TextDisplay(
                    "Nanobot is enabled, but mentions will not be handled until at least one text channel is allowed."
                )
            )
        separator = discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small)
        container.add_item(separator)
        container.add_item(
            discord.ui.TextDisplay(f"-# Page {self._page}/{self._total_pages()}")
        )

        enable_button = discord.ui.Button(
            label="Enable",
            custom_id="nanobot_enable",
            style=discord.ButtonStyle.success,
            disabled=self._policy.enabled,
        )
        enable_button.callback = self.enable
        disable_button = discord.ui.Button(
            label="Disable",
            custom_id="nanobot_disable",
            style=discord.ButtonStyle.danger,
            disabled=not self._policy.enabled,
        )
        disable_button.callback = self.disable
        container.add_item(discord.ui.ActionRow(enable_button, disable_button))

        add_select = discord.ui.ChannelSelect(
            custom_id="nanobot_add_channels",
            channel_types=[discord.ChannelType.text],
            placeholder="Add text channels allowed to mention Nanobot",
            min_values=1,
            max_values=_BATCH_LIMIT,
        )

        async def add_selected(interaction: discord.Interaction) -> None:
            await self.add_channels(interaction, tuple(add_select.values))

        add_select.callback = add_selected
        container.add_item(discord.ui.ActionRow(add_select))

        remove_select = discord.ui.ChannelSelect(
            custom_id="nanobot_remove_channels",
            channel_types=[discord.ChannelType.text],
            placeholder="Remove text channels from Nanobot mentions",
            min_values=1,
            max_values=_BATCH_LIMIT,
        )

        async def remove_selected(interaction: discord.Interaction) -> None:
            await self.remove_channels(interaction, tuple(remove_select.values))

        remove_select.callback = remove_selected
        container.add_item(discord.ui.ActionRow(remove_select))

        if self._total_pages() > 1:
            previous_button = discord.ui.Button(
                label="Previous",
                custom_id="nanobot_previous",
                disabled=self._page <= 1,
            )
            previous_button.callback = self.go_previous
            next_button = discord.ui.Button(
                label="Next",
                custom_id="nanobot_next",
                disabled=self._page >= self._total_pages(),
            )
            next_button.callback = self.go_next
            container.add_item(discord.ui.ActionRow(previous_button, next_button))
        self.add_item(container)

    async def _refresh_message(
        self, interaction: discord.Interaction, *, page_delta: int = 0
    ) -> None:
        self._policy = await self._policy_repository.get(self._guild_id)
        self._page = min(max(1, self._page + page_delta), self._total_pages())
        self._refresh_items()
        await interaction.response.edit_message(
            content=None,
            view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _ensure_callback_allowed(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await self._send_denial(
                interaction, "Nanobot settings are only available in a server."
            )
            return False
        if self._requires_administrator and not interaction.permissions.administrator:
            await self._send_denial(
                interaction, "Only server administrators can change Nanobot settings."
            )
            return False
        if not await self._owner_check.is_owner(interaction.user):
            await self._send_denial(interaction, self._authority_denial(changing=True))
            return False
        return True

    def _authority_denial(self, *, changing: bool) -> str:
        if self._requires_administrator:
            action = "change" if changing else "use"
            return f"Only the administrator who opened this Nanobot settings view can {action} it."
        if changing:
            return "Only the bot owner can change Nanobot settings."
        return "Only the bot owner can use these Nanobot settings."

    async def _send_denial(
        self, interaction: discord.Interaction, message: str
    ) -> None:
        await interaction.response.send_message(message, ephemeral=True)

    def _format_allowed_channels(self) -> str:
        channel_ids = sorted(self._policy.channel_ids, key=int)
        return ", ".join(map(self._format_channel, channel_ids)) or "none"

    def _page_channel_ids(self) -> tuple[ChannelId, ...]:
        channel_ids = tuple(sorted(self._policy.channel_ids, key=int))
        start = (self._page - 1) * _PAGE_SIZE
        return channel_ids[start : start + _PAGE_SIZE]

    def _total_pages(self) -> int:
        count = len(self._policy.channel_ids)
        return max(1, (count + _PAGE_SIZE - 1) // _PAGE_SIZE)

    def _format_channel(self, channel_id: ChannelId) -> str:
        channel = self._guild.get_channel(int(channel_id))
        if channel is None:
            return f"channel `{channel_id}`"

        safe_name = discord.utils.escape_mentions(
            discord.utils.escape_markdown(channel.name)
        )
        return f"`#{safe_name}` (`{channel_id}`)"

    def _text_channel_ids(
        self, channels: Iterable[SettingsChannel]
    ) -> tuple[ChannelId, ...]:
        return tuple(
            ChannelId(str(channel.id))
            for channel in channels
            if channel.type is discord.ChannelType.text
        )
