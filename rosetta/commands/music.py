import asyncio
import logging
import random
from queue import Empty
from typing import List

import discord
import pomice
import yt_dlp
from discord import app_commands
from discord.ext import commands, tasks

from rosetta.utils.player import CustomPlayer, NormalizeFilter

from ..utils.embeds import (
    ErrorEmbed,
    InfoEmbed,
    LeaveEmbed,
    NowPlayingEmbed,
    ProcessingEmbed,
    SearchEmbed,
    SuccessEmbed,
)

logger = logging.getLogger(__name__)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pomice = pomice.NodePool()
        asyncio.create_task(self.start_nodes())
    
    async def start_nodes(self):
        logger.info("Starting Pomice nodes...")
        await self.pomice.create_node(
            bot=self.bot,
            host="127.0.0.1",
            port=2333,
            password="youshallnotpass",
            identifier="MAIN",
        )
        logger.info("Pomice node 'MAIN' is ready!")

    async def _play(
        self,
        interaction: discord.Interaction,
        url: str,
        loop: str,
        shuffle: bool,
        top: bool,
    ):
        player = interaction.guild.voice_client if interaction.guild else None
        if player is None:
            if interaction.user.voice and interaction.user.voice.channel:
                player = await interaction.user.voice.channel.connect(cls=CustomPlayer)
                # await player.add_filter(NormalizeFilter(), fast_apply=True)
                await player.set_volume(10)

        results = await player.get_tracks(query=f"{url}", search_type=pomice.URLRegex.YOUTUBE_URL)

        if not results:
            logger.warning(f"No results found for search term: {url}")
            raise commands.CommandError("No results were found for that search term.")

        if isinstance(results, pomice.Playlist):
            tracks = results.tracks
            name = results.name
            uri = results.uri
            thumbnail = results.thumbnail
            logger.info(f"Enqueuing playlist: {name} ({len(tracks)} tracks) for guild {interaction.guild_id}")
        else:
            tracks = results
            name = tracks[0].title
            uri = tracks[0].uri
            thumbnail = tracks[0].thumbnail
            logger.info(f"Enqueuing track: {name} for guild {interaction.guild_id}")

        # loop
        if loop == "Off":
            if player.queue.loop_mode:
                player.queue.disable_loop()
        elif loop == "One":
            player.queue.set_loop_mode(pomice.LoopMode.TRACK)
        elif loop == "Queue":
            player.queue.set_loop_mode(pomice.LoopMode.QUEUE)
        else:
            raise NotImplementedError()

        # top
        if top:
            for track in tracks[::-1]:
                player.queue.put_at_front(track)
        else:
            player.queue.extend(tracks)
        
        # shuffle
        if shuffle:
            player.queue.shuffle()
        
        if not player.is_playing:
            track = player.queue.get()
            await player.play(track)
            
        embed = SuccessEmbed(
            interaction.user, f"Enqueued [**{name}**]({uri})"
        )
        embed.set_thumbnail(url=thumbnail)
        
        return embed

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
        logger.info(f"Play command called by {interaction.user} in guild {interaction.guild_id} with url: {url}")
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
        logger.info(f"Loop command called by {interaction.user} in guild {interaction.guild_id} with mode: {loop}")
        player = await self.ensure_player(interaction)

        if loop == "Off":
            if player.queue.loop_mode:
                player.queue.disable_loop()
        elif loop == "One":
            player.queue.set_loop_mode(pomice.LoopMode.TRACK)
        elif loop == "Queue":
            player.queue.set_loop_mode(pomice.LoopMode.QUEUE)
        else:
            raise NotImplementedError()
        
        await interaction.response.send_message(
            embed=SuccessEmbed(self.bot.user, f"Current loop: **{player.queue.loop_mode}**")
        )

    @app_commands.command(name="search", description="Search in Youtube")
    @app_commands.describe(keyword="keyword")
    async def search(self, interaction: discord.Interaction, keyword: str):
        logger.info(f"Search command called by {interaction.user} in guild {interaction.guild_id} with keyword: {keyword}")
        await interaction.response.defer()
        tracks = await self.pomice.get_node().get_tracks(keyword)
        await interaction.followup.send(
            embed=SearchEmbed(self.bot.user, keyword, tracks)
        )

    async def do_shuffle(self, interaction: discord.Interaction, ephemeral: bool = False):
        """Helper method to shuffle the queue"""
        logger.info(f"Shuffle requested by {interaction.user} in guild {interaction.guild_id}")
        player = await self.ensure_player(interaction)
        player.queue.shuffle()
        await interaction.response.send_message(
            embed=SuccessEmbed(self.bot.user, "Shuffle complete"), ephemeral=ephemeral
        )

    async def do_skip(self, interaction: discord.Interaction, ephemeral: bool = False):
        """Helper method to skip to the next song"""
        logger.info(f"Skip requested by {interaction.user} in guild {interaction.guild_id}")
        player = await self.ensure_player(interaction)
        await interaction.response.defer(ephemeral=ephemeral)
        try:
            track = player.queue.get_queue()[0]
            logger.info(f"Skipping to next track: {track.title} in guild {interaction.guild_id}")
            await player.stop()
            embed = SuccessEmbed(
                self.bot.user, f"Skipped to [**{track.title}**]({track.uri})"
            )
            embed.set_thumbnail(url=track.thumbnail)
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        except Empty:
            logger.info(f"Skip requested but queue is empty in guild {interaction.guild_id}")
            await interaction.followup.send(
                embed=SuccessEmbed(self.bot.user, "No song left")
            )

    @app_commands.command(name="shuffle", description="Shuffle")
    @app_commands.describe(ephemeral="hide response")
    async def shuffle(self, interaction: discord.Interaction, ephemeral: bool = False):
        await self.do_shuffle(interaction, ephemeral)

    @app_commands.command(name="skip", description="Skip to next song")
    @app_commands.describe(ephemeral="hide response")
    async def skip(self, interaction: discord.Interaction, ephemeral: bool = False):
        await self.do_skip(interaction, ephemeral)

    @app_commands.command(name="leave", description="Leave current channel")
    async def leave(self, interaction: discord.Interaction):
        logger.info(f"Leave command called by {interaction.user} in guild {interaction.guild_id}")
        player = await self.ensure_player(interaction)
        await player.destroy()
        await interaction.response.send_message(embed=LeaveEmbed(self.bot.user))

    @app_commands.command(name="nowplaying", description="Show the song playing now")
    @app_commands.describe(realtime="enable realtime updates")
    async def nowplaying(
        self, interaction: discord.Interaction, realtime: bool = False
    ):
        await interaction.response.defer()
        player = await self.ensure_player(interaction)
        
        await interaction.followup.send(
            embed=NowPlayingEmbed(
                track=player.current, queue=player.queue
            ),
        )

    async def ensure_voice(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client if interaction.guild else None
        if voice_client is None:
            if not interaction.user.voice:
                logger.warning(f"User {interaction.user} not in voice channel in guild {interaction.guild_id}")
                raise commands.CommandError("You are not connected to a voice channel.")
        return voice_client
    
    async def ensure_player(self, interaction: discord.Interaction) -> CustomPlayer:
        player = interaction.guild.voice_client if interaction.guild else None
        if not player:
            logger.warning(f"Player not found for guild {interaction.guild_id}")
            raise commands.CommandError("The bot is not playing")
        return player
    
    @commands.Cog.listener("on_pomice_track_end")
    async def on_pomice_track_end(self, player: CustomPlayer, track: pomice.Track, reason: str):
        logger.info(f"Track ended in guild {player.guild.id}: {track.title} (Reason: {reason})")
        try:
            next_track = player.queue.get()
            logger.info(f"Playing next track in guild {player.guild.id}: {next_track.title}")
            await player.play(next_track)
        except pomice.QueueEmpty:
            logger.info(f"Queue empty in guild {player.guild.id}, destroying player")
            await player.destroy()