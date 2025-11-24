import asyncio
import random
from queue import Empty
from typing import List

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands, tasks

from ..utils.embeds import (
    ErrorEmbed,
    InfoEmbed,
    LeaveEmbed,
    NowPlayingEmbed,
    ProcessingEmbed,
    SearchEmbed,
    SuccessEmbed,
)
from ..utils.subscriptions import Subscription
from ..utils.track import Track


class Player(commands.Cog):
    subscriptions = Subscription()

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _play(
        self,
        interaction: discord.Interaction,
        url: str,
        loop: str,
        shuffle: bool,
        top: bool,
    ):
        try:
            tracks = await Track.from_url(url, interaction.user)
        except Exception as e:
            raise commands.CommandError(f"[yt-dlp] {e}")

        voice_client = interaction.guild.voice_client if interaction.guild else None
        if voice_client is None:
            if interaction.user.voice and interaction.user.voice.channel:
                voice_client = await interaction.user.voice.channel.connect()

        if shuffle:
            random.shuffle(tracks["tracks"])

        subscription = self.subscriptions.get(interaction.guild_id)
        if subscription:
            subscription.addTracks(tracks["tracks"], top)
        else:
            self.subscriptions.createQueue(
                self.bot.user,
                interaction.guild_id,
                interaction.channel,
                voice_client,
                tracks["tracks"],
                loop,
            )
        embed = SuccessEmbed(
            interaction.user, f"Enqueued [**{tracks['title']}**]({tracks['url']})"
        )
        embed.set_thumbnail(url=tracks["thumbnail"])
        return embed

    async def _search(self, interaction: discord.Interaction, keyword: str):
        options = {
            "extractor_retries": 1,
            "quiet": True,
            "noplaylist": True,
            "ignoreerrors": True,
            "extract_flat": True,
        }
        with yt_dlp.YoutubeDL(options) as ytdl:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(
                None,
                lambda: ytdl.extract_info(f"ytsearch25:{keyword}", download=False),
            )
            data = [
                entry
                for entry in data.get("entries", [])
                if entry.get("ie_key") == "Youtube"
            ]
            tracks = [Track(d, interaction.user) for d in data]
            return tracks

    @app_commands.command(name="play", description="Play Youtube music")
    @app_commands.describe(
        url="url",
        loop="loop",
        shuffle="shuffle the playlist",
        top="add to the top of queue",
    )
    @app_commands.choices(
        loop=[
            app_commands.Choice(name="Off", value="Off"),
            app_commands.Choice(name="One", value="One"),
            app_commands.Choice(name="Queue", value="Queue"),
        ]
    )
    async def play(
        self,
        interaction: discord.Interaction,
        url: str,
        loop: str = "Off",
        shuffle: bool = False,
        top: bool = False,
    ):
        await self.ensure_voice(interaction)
        await interaction.response.defer()
        message = await interaction.followup.send(
            embed=ProcessingEmbed(self.bot.user), wait=True
        )
        embed = await self._play(interaction, url, loop, shuffle, top)
        await message.edit(embed=embed)

    @app_commands.command(name="loop", description="Set loop")
    @app_commands.describe(loop="loop mode")
    @app_commands.choices(
        loop=[
            app_commands.Choice(name="Off", value="Off"),
            app_commands.Choice(name="One", value="One"),
            app_commands.Choice(name="Queue", value="Queue"),
        ]
    )
    async def loop_command(self, interaction: discord.Interaction, loop: str = "Off"):
        await self.ensure_subscription(interaction)
        subscription = self.subscriptions.get(interaction.guild_id)
        subscription.loop = loop
        await interaction.response.send_message(
            embed=SuccessEmbed(self.bot.user, f"Current loop: **{subscription.loop}**")
        )

    @app_commands.command(name="search", description="Search in Youtube")
    @app_commands.describe(keyword="keyword")
    async def search(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer()
        tracks = await self._search(interaction, keyword)
        await interaction.followup.send(
            embed=SearchEmbed(self.bot.user, keyword, tracks),
            view=SearchSelectView(self, tracks, interaction),
        )

    @app_commands.command(name="shuffle", description="Shuffle")
    @app_commands.describe(ephemeral="hide response")
    async def shuffle(self, interaction: discord.Interaction, ephemeral: bool = False):
        await self.ensure_subscription(interaction)
        subscription = self.subscriptions.get(interaction.guild_id)
        random.shuffle(subscription.queue)
        await interaction.response.send_message(
            embed=SuccessEmbed(self.bot.user, "Shuffle complete"), ephemeral=ephemeral
        )

    @app_commands.command(name="skip", description="Skip to next song")
    @app_commands.describe(ephemeral="hide response")
    async def skip(self, interaction: discord.Interaction, ephemeral: bool = False):
        await self.ensure_subscription(interaction)
        await interaction.response.defer(ephemeral=ephemeral)
        subscription = self.subscriptions.get(interaction.guild_id)
        try:
            track = await subscription.skip()
            embed = SuccessEmbed(
                self.bot.user, f"Skipped to [**{track.title}**]({track.url})"
            )
            embed.set_thumbnail(url=track.thumbnail)
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        except Empty:
            await interaction.followup.send(
                embed=SuccessEmbed(self.bot.user, "No song left")
            )

    @app_commands.command(name="leave", description="Leave current channel")
    async def leave(self, interaction: discord.Interaction):
        await self.ensure_subscription(interaction)
        subscription = self.subscriptions.get(interaction.guild_id)
        await subscription.leave(message=False)
        await interaction.response.send_message(embed=LeaveEmbed(self.bot.user))

    @app_commands.command(name="nowplaying", description="Show the song playing now")
    @app_commands.describe(realtime="enable realtime updates")
    async def nowplaying(
        self, interaction: discord.Interaction, realtime: bool = False
    ):
        await interaction.response.defer()
        subscription = self.subscriptions.get(interaction.guild_id)
        if not subscription:
            await interaction.followup.send(
                embed=ErrorEmbed(self.bot.user, "Not playing now.")
            )
            return
        if subscription and not subscription.checkLock:
            if realtime:
                message = await interaction.followup.send(
                    embed=NowPlayingEmbed(
                        track=subscription.nowPlaying, queue=subscription.queue
                    ),
                    view=NowPlayingView(self),
                    wait=True,
                )
                self.updateNowPlaying.start(interaction.guild_id, message.id)
            else:
                await interaction.followup.send(
                    embed=NowPlayingEmbed(
                        track=subscription.nowPlaying, queue=subscription.queue
                    ),
                )

    @tasks.loop(seconds=1)
    async def updateNowPlaying(self, guild_id, message_id):
        subscription = self.subscriptions.get(guild_id)
        if not subscription:
            self.updateNowPlaying.cancel()
        if subscription and not subscription.checkLock:
            message = self.bot.get_message(message_id)
            if message:
                await message.edit(
                    embed=NowPlayingEmbed(
                        track=subscription.nowPlaying, queue=subscription.queue
                    )
                )

    async def ensure_voice(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client if interaction.guild else None
        if voice_client is None:
            if not interaction.user.voice:
                raise commands.CommandError("You are not connected to a voice channel.")

    async def ensure_subscription(self, interaction: discord.Interaction):
        await self.ensure_voice(interaction)
        subscription = self.subscriptions.get(interaction.guild_id)
        if not subscription:
            raise commands.CommandError("You are not playing in this guild.")

    @commands.Cog.listener("on_voice_state_update")
    async def lonelyListener(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if before.channel:
            subscription = self.subscriptions.get(before.channel.guild.id)
            if subscription:
                if member != self.bot.user:
                    if len(before.channel.voice_states) == 1:
                        self.time = 0
                        self.lonelyTimer.start(subscription.voiceClient.channel)
                        await subscription.messageChannel.send(
                            embed=InfoEmbed(
                                self.bot.user,
                                ":pleading_face: Felling lonely. I'll leave in **60** seconds",
                            )
                        )
        if after.channel:
            subscription = self.subscriptions.get(after.channel.guild.id)
            if subscription:
                if member != self.bot.user:
                    if after.channel == subscription.voiceClient.channel:
                        if self.lonelyTimer.is_running():
                            self.lonelyTimer.cancel()
                            await subscription.messageChannel.send(
                                embed=InfoEmbed(
                                    self.bot.user, f"<@{member.id}> is back with me"
                                )
                            )

    @tasks.loop(seconds=1)
    async def lonelyTimer(self, channel: discord.VoiceChannel):
        self.time += 1
        if self.time >= 60:
            subscription = self.subscriptions.get(channel.guild.id)
            await subscription.leave()
            self.lonelyTimer.cancel()


class SearchSelectView(discord.ui.View):
    def __init__(
        self,
        player: Player,
        tracks: List[Track],
        interaction: discord.Interaction,
        *,
        timeout=60,
    ):
        super().__init__(timeout=timeout)
        self.add_item(SearchSelect(player, tracks, interaction))
        self.add_item(
            SearchButton(player, tracks, interaction, label="Search", emoji="🔎")
        )
        self.add_item(ToggleButton(emoji="🔝", custom_id="Top"))


class SearchModal(discord.ui.Modal):
    def __init__(
        self, player: Player, tracks: List[Track], interaction: discord.Interaction
    ) -> None:
        super().__init__(title="Search Model")
        self.add_item(
            discord.ui.TextInput(label="Keyword", placeholder="Enter search keyword")
        )
        self.player = player
        self.tracks = tracks
        self.original_interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        keyword = self.children[0].value
        await interaction.response.edit_message(
            embed=InfoEmbed(self.player.bot.user, "Processing"),
        )
        tracks = await self.player._search(interaction, keyword)
        await interaction.message.edit(
            embed=SearchEmbed(self.player.bot.user, keyword, tracks),
            view=SearchSelectView(self.player, tracks, interaction),
        )
        await interaction.followup.send(
            embed=SuccessEmbed(self.player.bot.user, f'Searched for "{keyword}"'),
            ephemeral=True,
        )


class SearchSelect(discord.ui.Select):
    def __init__(
        self, player: Player, tracks: List[Track], interaction: discord.Interaction
    ):
        options = [
            discord.SelectOption(
                label=track.title,
                emoji="🎵",
                description=track.channel,
                value=track.url,
            )
            for track in tracks
        ]
        super().__init__(
            placeholder="Select an option", max_values=1, min_values=1, options=options
        )
        self.player = player
        self.tracks = tracks
        self.original_interaction = interaction

    async def callback(self, interaction: discord.Interaction):
        top = (
            True
            if self.view.get_item("Top").style == discord.ButtonStyle.success
            else False
        )
        self.view.clear_items()
        await interaction.message.edit(view=self.view)
        await interaction.response.defer()
        message = await interaction.followup.send(
            embed=ProcessingEmbed(self.player.bot.user), wait=True
        )

        await self.player.ensure_voice(interaction)
        embed = await self.player._play(interaction, self.values[0], "Off", False, top)
        await message.edit(embed=embed)


class SearchButton(discord.ui.Button):
    def __init__(
        self,
        player: Player,
        tracks: List[Track],
        interaction: discord.Interaction,
        *,
        style=discord.ButtonStyle.primary,
        label=None,
        emoji=None,
    ):
        super().__init__(style=style, label=label, emoji=emoji)
        self.player = player
        self.tracks = tracks
        self.original_interaction = interaction

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            SearchModal(self.player, self.tracks, interaction)
        )


class ToggleButton(discord.ui.Button):
    def __init__(
        self,
        *,
        style=discord.ButtonStyle.secondary,
        label=None,
        emoji=None,
        custom_id=None,
    ):
        super().__init__(style=style, label=label, emoji=emoji, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        if self.style == discord.ButtonStyle.success:
            self.style = discord.ButtonStyle.secondary
            res = "False"
        elif self.style == discord.ButtonStyle.secondary:
            self.style = discord.ButtonStyle.success
            res = "True"

        await interaction.message.edit(view=self.view)
        await interaction.response.send_message(
            embed=SuccessEmbed(interaction.user, f"{self.custom_id} switched to {res}"),
            ephemeral=True,
        )


class NowPlayingView(discord.ui.View):
    def __init__(self, player: Player):
        self.player = player
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Skip", custom_id="skip", style=discord.ButtonStyle.primary, emoji="⏩"
    )
    async def skip(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.player.skip(interaction, True)

    @discord.ui.button(
        label="Shuffle",
        custom_id="shuffle",
        style=discord.ButtonStyle.primary,
        emoji="🔀",
    )
    async def shuffle(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await self.player.shuffle(interaction, True)

    @discord.ui.button(
        label="Stop Sync",
        custom_id="stop-sync",
        style=discord.ButtonStyle.primary,
        emoji="♾️",
    )
    async def stopSync(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        self.player.updateNowPlaying.cancel()
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
