import logging
import math

import discord
from discord.ext import commands

from ..config import EmojiConfig
from ..player import CustomPlayer

logger = logging.getLogger("rosetta")


class NowPlayingView(discord.ui.LayoutView):
    def __init__(self, player: CustomPlayer, user: discord.User | discord.Member, accent_color: int = 0x229AE0):
        super().__init__()
        self.user = user
        self.accent_color = accent_color
        self.page_size = 10
        self.container = self.construct_container(player)
        self.add_item(self.container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "You cannot interact with this view.", ephemeral=True
            )
            return False
        return True

    def refresh_callback(self):
        async def _callback(interaction: discord.Interaction):
            player = await self.ensure_player(interaction)

            new_container = self.construct_container(player)
            self.refresh_item(self.container, new_container)
            self.container = new_container

            await interaction.response.edit_message(view=self)

        return _callback

    def pagination_callback(self, current_page: int = 1):
        async def _callback(interaction: discord.Interaction):
            player = await self.ensure_player(interaction)
            total_pages = (len(player.queue) + self.page_size - 1) // self.page_size
            new_page = current_page
            if interaction.data["custom_id"] == "next":
                new_page = min(current_page + 1, total_pages)
            elif interaction.data["custom_id"] == "previous":
                new_page = max(current_page - 1, 1)

            new_container = self.construct_container(player, new_page)
            self.refresh_item(self.container, new_container)
            self.container = new_container

            await interaction.response.edit_message(view=self)

        return _callback

    def select_callback(self):
        async def _callback(interaction: discord.Interaction):
            player = await self.ensure_player(interaction)

            result = interaction.data["values"][0]
            track = player.queue.skip_to(int(result))
            await player.play(track)

            new_container = self.construct_container(player)
            self.refresh_item(self.container, new_container)
            self.container = new_container

            await interaction.response.edit_message(view=self)

        return _callback

    def _format_time(self, milliseconds: int) -> str:
        seconds = int(milliseconds / 1000)
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def _get_time_display(self, position_ms: int, duration_ms: int) -> tuple[str, str]:
        """Convert milliseconds to formatted time strings (mm:ss)"""
        currentMinute = int(position_ms / 60000)
        currentSecond = int(position_ms / 1000) % 60
        durationMinute = int(duration_ms / 60000)
        durationSecond = int(duration_ms / 1000) % 60

        times = (currentMinute, currentSecond, durationMinute, durationSecond)
        timesWithZeros = [f"0{t}" if t < 10 else t for t in times]

        return (
            f"{timesWithZeros[0]}:{timesWithZeros[1]}",
            f"{timesWithZeros[2]}:{timesWithZeros[3]}",
        )

    def _get_progress_bar(self, position_ms: int, duration_ms: int) -> str:
        """Generate a progress bar based on current position and duration"""
        if duration_ms == 0:
            return ""

        progress = math.floor(position_ms * 10 / duration_ms)

        # [========]
        if progress == 0:
            return (
                EmojiConfig.get("progress_start_0")
                + EmojiConfig.get("progress") * 8
                + EmojiConfig.get("progress_end")
            )
        elif progress == 1:
            return (
                EmojiConfig.get("progress_start")
                + EmojiConfig.get("progress_mix")
                + EmojiConfig.get("progress") * 7
                + EmojiConfig.get("progress_end")
            )
        elif progress >= 10:
            return (
                EmojiConfig.get("progress_start")
                + EmojiConfig.get("progress_fill") * 8
                + EmojiConfig.get("progress_fill_end")
            )
        else:
            return (
                EmojiConfig.get("progress_start")
                + EmojiConfig.get("progress_fill") * (progress - 1)
                + EmojiConfig.get("progress_mix")
                + EmojiConfig.get("progress") * (8 - progress)
                + EmojiConfig.get("progress_end")
            )

    def construct_container(self, player: CustomPlayer, page: int = 1):
        track = player.current
        queue = player.queue
        current_time, duration_time = self._get_time_display(
            player.position, track.length
        )
        progress_bar = self._get_progress_bar(player.position, track.length)

        title = discord.ui.TextDisplay(f"{EmojiConfig.get('youtube')} **Now Playing**")
        description = discord.ui.TextDisplay(f"[**{track.title}**]({track.uri})")
        progress = discord.ui.TextDisplay(
            f"`{current_time}` {progress_bar} `{duration_time}`"
        )
        thumbnail = discord.ui.Thumbnail(track.thumbnail)
        section = discord.ui.Section(title, description, progress, accessory=thumbnail)
        container = discord.ui.Container(
            section,
            discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.large),
            accent_color=self.accent_color,
        )

        if not queue.is_empty:
            start_idx = (page - 1) * self.page_size
            end_idx = min(start_idx + self.page_size, len(queue))
            queue_list = discord.ui.TextDisplay(
                f"💭 Next ({len(queue)} left)\n{'\n'.join([f'{i + 1}. [{t.title}]({t.uri}) `{self._format_time(t.length)}`' for i, t in enumerate(queue.peek_n(end_idx, _start=start_idx), start=start_idx)])}"
            )
            container.add_item(queue_list)

            options = [
                discord.SelectOption(label=t.title, description=t.author, value=i)
                for i, t in enumerate(
                    queue.peek_n(end_idx, _start=start_idx), start=start_idx
                )
            ]
            song_select = discord.ui.Select(
                custom_id="song_select", placeholder="Skip to...", options=options
            )
            song_select.callback = self.select_callback()
            container.add_item(discord.ui.ActionRow(song_select))

        refresh_button = discord.ui.Button(
            label="Refresh", custom_id="refresh", style=discord.ButtonStyle.primary
        )
        refresh_button.callback = self.refresh_callback()
        actionrow = discord.ui.ActionRow(refresh_button)

        total_pages = (len(queue) + self.page_size - 1) // self.page_size
        if total_pages > 1:
            previous_button = discord.ui.Button(
                label="Previous", custom_id="previous", disabled=page <= 1
            )
            previous_button.callback = self.pagination_callback(page)
            actionrow.add_item(previous_button)
            next_button = discord.ui.Button(
                label="Next", custom_id="next", disabled=page >= total_pages
            )
            next_button.callback = self.pagination_callback(page)
            actionrow.add_item(next_button)
        container.add_item(actionrow)

        return container

    def refresh_item(self, old_item: discord.ui.Item, new_item: discord.ui.Item):
        new_item._update_view(self)
        self._swap_item(old_item, new_item, "")
        del old_item

    async def ensure_voice(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client if interaction.guild else None
        if voice_client is None:
            if not interaction.user.voice:
                logging.warning(
                    f"User {interaction.user} not in voice channel in guild {interaction.guild_id}"
                )
                raise commands.CommandError("You are not connected to a voice channel.")
        return voice_client

    async def ensure_player(self, interaction: discord.Interaction) -> CustomPlayer:
        player = interaction.guild.voice_client if interaction.guild else None
        if not player:
            logging.warning(f"Player not found for guild {interaction.guild_id}")
            raise commands.CommandError("The bot is not playing")
        return player
