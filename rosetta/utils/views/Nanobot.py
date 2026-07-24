from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final, Protocol

import discord

from rosetta.utils.nanobot_policy import ChannelId, GuildId, GuildPolicy

_BATCH_LIMIT: Final = 25
_ACCENT_COLOR: Final = 0x229AE0


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


class NanobotSettingsView(discord.ui.View):
    def __init__(
        self,
        *,
        policy_repository: NanobotPolicyStore,
        guild: SettingsGuild,
        user: SettingsUser,
        policy: GuildPolicy,
    ) -> None:
        super().__init__(timeout=300)
        self._policy_repository = policy_repository
        self._guild = guild
        self._guild_id = GuildId(str(guild.id))
        self._user_id = user.id
        self._policy = policy
        self._refresh_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self._user_id:
            return True

        await self._send_denial(
            interaction,
            "Only the administrator who opened these Nanobot settings can use this view.",
        )
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

    def _refresh_items(self) -> None:
        self.clear_items()

        enable_button = discord.ui.Button(
            label="Enable",
            custom_id="nanobot_enable",
            style=discord.ButtonStyle.success,
            disabled=self._policy.enabled,
        )
        enable_button.callback = self.enable
        self.add_item(enable_button)

        disable_button = discord.ui.Button(
            label="Disable",
            custom_id="nanobot_disable",
            style=discord.ButtonStyle.danger,
            disabled=not self._policy.enabled,
        )
        disable_button.callback = self.disable
        self.add_item(disable_button)

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
        self.add_item(add_select)

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
        self.add_item(remove_select)

    async def _refresh_message(self, interaction: discord.Interaction) -> None:
        self._policy = await self._policy_repository.get(self._guild_id)
        self._refresh_items()
        await interaction.response.edit_message(
            content=self.render_text(),
            view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _ensure_callback_allowed(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await self._send_denial(
                interaction,
                "Nanobot settings are only available in a server.",
            )
            return False
        if not interaction.permissions.administrator:
            await self._send_denial(
                interaction,
                "Only server administrators can change Nanobot settings.",
            )
            return False
        if interaction.user.id != self._user_id:
            await self._send_denial(
                interaction,
                "Only the administrator who opened these Nanobot settings can use this view.",
            )
            return False
        return True

    async def _send_denial(
        self, interaction: discord.Interaction, message: str
    ) -> None:
        await interaction.response.send_message(message, ephemeral=True)

    def _format_allowed_channels(self) -> str:
        if not self._policy.channel_ids:
            return "none"
        return ", ".join(
            self._format_channel(channel_id)
            for channel_id in sorted(self._policy.channel_ids, key=int)
        )

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
