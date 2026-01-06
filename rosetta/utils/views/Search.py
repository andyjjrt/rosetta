import logging
from typing import TYPE_CHECKING, List

import discord
import pomice
from discord.ext import commands

from rosetta.utils.log import LogContext, PydanticAdapter

if TYPE_CHECKING:
    from rosetta.commands.music import Music


from ..player import CustomPlayer

logger = logging.getLogger("rosetta")


class SearchView(discord.ui.LayoutView):
    def __init__(
        self,
        bot: commands.Bot,
        keyword: str,
        tracks: List[pomice.Track] | pomice.Playlist,
        accent_color: int = 0x229AE0,
    ):
        super().__init__(timeout=300)
        self.bot = bot
        self.keyword = keyword
        self.accent_color = accent_color
        self.page_size = 5

        if isinstance(tracks, pomice.Playlist):
            self.tracks = tracks.tracks
        else:
            self.tracks = tracks

        self.container = self.construct_container()
        self.add_item(self.container)

    def refresh_item(self, old_item: discord.ui.Item, new_item: discord.ui.Item):
        new_item._update_view(self)
        self._swap_item(old_item, new_item, "")
        del old_item

    def _format_time(self, milliseconds: int) -> str:
        seconds = int(milliseconds / 1000)
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def pagination_callback(self, current_page: int = 1):
        async def _callback(interaction: discord.Interaction):
            total_pages = (len(self.tracks) + self.page_size - 1) // self.page_size
            new_page = current_page

            if interaction.data["custom_id"] == "next":
                new_page = min(current_page + 1, total_pages)
            elif interaction.data["custom_id"] == "previous":
                new_page = max(current_page - 1, 1)

            new_container = self.construct_container(new_page)
            self.refresh_item(self.container, new_container)
            self.container = new_container

            await interaction.response.edit_message(view=self)

        return _callback

    def select_callback(self):
        async def _callback(interaction: discord.Interaction):
            ctx_data = LogContext.from_interaction(interaction)
            adapter = PydanticAdapter(logger, ctx_data)
            interaction.extras["logger"] = adapter

            url = interaction.data["values"][0]
            music: "Music" = self.bot.cogs.get("Music")
            embed = await music._play(interaction, url)

            await interaction.response.send_message(embed=embed)

        return _callback

    def construct_container(self, page: int = 1):
        total_tracks = len(self.tracks)
        total_pages = (total_tracks + self.page_size - 1) // self.page_size

        # Header
        header = discord.ui.TextDisplay(f'🔍 **Search result of "{self.keyword}"')

        container = discord.ui.Container(
            header,
            discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small),
            accent_color=self.accent_color,
        )

        # Paginated track list
        start_idx = (page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, total_tracks)
        page_tracks = self.tracks[start_idx:end_idx]

        options = []

        for i, track in enumerate(page_tracks, start=start_idx):
            track_detail = discord.ui.TextDisplay(
                f"{i + 1}. [{track.title}]({track.uri}) `{self._format_time(track.length)}`"
            )
            options.append(
                discord.SelectOption(
                    label=track.title, description=track.author, value=track.uri
                )
            )
            section = discord.ui.Section(
                track_detail, accessory=discord.ui.Thumbnail(track.thumbnail)
            )
            container.add_item(section)
            if i < end_idx - 1:
                container.add_item(
                    discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small)
                )

        song_select = discord.ui.Select(
            custom_id="song_select", placeholder="Add...", options=options
        )
        song_select.callback = self.select_callback()

        # Footer with page info
        container.add_item(
            discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small)
        )
        footer = discord.ui.TextDisplay(f"-# Page {page}/{total_pages}")
        container.add_item(footer)

        container.add_item(discord.ui.ActionRow(song_select))

        if total_pages > 1:
            actionrow = discord.ui.ActionRow()
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
            if interaction.user.voice and interaction.user.voice.channel:
                player = await interaction.user.voice.channel.connect(cls=CustomPlayer)
                await player.set_volume(10)
        return player
