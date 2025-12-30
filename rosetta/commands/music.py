import asyncio
import logging
from queue import Empty
from typing import List

import discord
import pomice
from discord import app_commands
from discord.ext import commands

from rosetta.utils.views import NowPlayingView
from rosetta.utils.config import LavalinkConfig
from rosetta.utils.player import CustomPlayer, LoopMode

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


def get_k8s_lavalink_endpoints() -> list[dict]:
    """
    Discover Lavalink nodes from Kubernetes Endpoints.
    Returns a list of dicts with host, port, password, and identifier.
    """
    try:
        from kubernetes import client
        from kubernetes import config as k8s_config

        # Try in-cluster config first (when running inside k8s)
        try:
            k8s_config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except k8s_config.ConfigException:
            # Fall back to kubeconfig (for local development with k8s)
            k8s_config.load_kube_config()
            logger.info("Loaded kubeconfig for Kubernetes access")

        v1 = client.CoreV1Api()
        namespace = LavalinkConfig.K8S_NAMESPACE
        service_name = LavalinkConfig.K8S_SERVICE_NAME
        port = LavalinkConfig.K8S_SERVICE_PORT
        password = LavalinkConfig.PASSWORD

        # Get endpoints for the lavalink service
        endpoints = v1.read_namespaced_endpoints(name=service_name, namespace=namespace)

        nodes = []
        if endpoints.subsets:
            for subset in endpoints.subsets:
                if subset.addresses:
                    for address in subset.addresses:
                        node_id = address.ip
                        node_name = address.nodeName
                        if address.targetRef:
                            node_id = address.targetRef.name
                        nodes.append(
                            {
                                "host": address.ip,
                                "port": port,
                                "password": password,
                                "identifier": node_id,
                                "nodeName": node_name,
                            }
                        )
                        logger.info(
                            f"Discovered Lavalink node: {node_id} at {address.ip}:{port} in {node_name}"
                        )

        if not nodes:
            logger.warning(f"No Lavalink endpoints found in {namespace}/{service_name}")

        return nodes

    except ImportError:
        logger.error("kubernetes package not installed, cannot use k8s discovery")
        return []
    except Exception as e:
        logger.error(f"Failed to discover Lavalink nodes from Kubernetes: {e}")
        return []


def get_local_lavalink_endpoints() -> list[dict]:
    """
    Get Lavalink node configuration for local development.
    Returns a list with a single node based on environment config.
    """
    return [
        {
            "host": LavalinkConfig.HOST,
            "port": LavalinkConfig.PORT,
            "password": LavalinkConfig.PASSWORD,
            "identifier": "MAIN",
            "nodeName": "localhost",
        }
    ]


def get_nodes() -> list[dict]:
    if LavalinkConfig.DISCOVERY_MODE == "k8s":
        nodes = get_k8s_lavalink_endpoints()
        if not nodes:
            logger.warning("No k8s nodes found, falling back to local config")
            nodes = get_local_lavalink_endpoints()
    else:
        nodes = get_local_lavalink_endpoints()
    return nodes


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pomice = pomice.NodePool()
        asyncio.create_task(self.start_nodes())

    async def start_nodes(self):
        """
        Start Pomice nodes based on discovery mode.
        - "k8s": Auto-discover Lavalink nodes from Kubernetes Endpoints
        - "local": Use local configuration from environment variables
        """
        logger.info(
            f"Starting Pomice nodes (discovery mode: {LavalinkConfig.DISCOVERY_MODE})..."
        )

        nodes = get_nodes()
        for node in nodes:
            try:
                await self.pomice.create_node(
                    bot=self.bot,
                    host=node["host"],
                    port=node["port"],
                    password=node["password"],
                    identifier=node["identifier"],
                )
                logger.info(
                    f"Pomice node '{node['identifier']}' is ready at {node['host']}:{node['port']}"
                )
            except Exception as e:
                logger.error(f"Failed to create node '{node['identifier']}': {e}")

        if not self.pomice.nodes:
            logger.error("No Lavalink nodes available!")

    async def remove_nodes(self):
        await self.pomice.disconnect()

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
                await player.set_volume(10)

        results = await player.get_tracks(
            query=f"{url}", search_type=pomice.URLRegex.YOUTUBE_URL
        )

        if not results:
            logger.warning(f"No results found for search term: {url}")
            raise commands.CommandError("No results were found for that search term.")

        if isinstance(results, pomice.Playlist):
            tracks = results.tracks
            name = results.name
            uri = results.uri
            thumbnail = results.thumbnail
            logger.info(
                f"Enqueuing playlist: {name} ({len(tracks)} tracks) for guild {interaction.guild_id}"
            )
        else:
            tracks = results
            name = tracks[0].title
            uri = tracks[0].uri
            thumbnail = tracks[0].thumbnail
            logger.info(f"Enqueuing track: {name} for guild {interaction.guild_id}")

        # top
        if top:
            player.queue.add_front(tracks)
        else:
            player.queue.add(tracks)

        # shuffle
        if shuffle:
            player.queue.shuffle()

        # loop
        if loop == "Off":
            player.queue.set_loop(LoopMode.NONE)
        elif loop == "One":
            player.queue.set_loop(LoopMode.ONE)
        elif loop == "Queue":
            player.queue.set_loop(LoopMode.QUEUE)
        else:
            raise NotImplementedError()

        if not player.is_playing:
            track = player.queue.get()
            await player.play(track)

        embed = SuccessEmbed(interaction.user, f"Enqueued [**{name}**]({uri})")
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
        logger.info(
            f"Play command called by {interaction.user} in guild {interaction.guild_id} with url: {url}"
        )
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
        logger.info(
            f"Loop command called by {interaction.user} in guild {interaction.guild_id} with mode: {loop}"
        )
        player = await self.ensure_player(interaction)

        if loop == "Off":
            player.queue.set_loop(LoopMode.NONE)
        elif loop == "One":
            player.queue.set_loop(LoopMode.ONE)
        elif loop == "Queue":
            player.queue.set_loop(LoopMode.QUEUE)
        else:
            raise NotImplementedError()

        await interaction.response.send_message(
            embed=SuccessEmbed(self.bot.user, f"Current loop: **{loop}**")
        )

    @app_commands.command(name="search", description="Search in Youtube")
    @app_commands.describe(keyword="keyword")
    async def search(self, interaction: discord.Interaction, keyword: str):
        logger.info(
            f"Search command called by {interaction.user} in guild {interaction.guild_id} with keyword: {keyword}"
        )
        await interaction.response.defer()
        tracks = await self.pomice.get_node().get_tracks(keyword)
        await interaction.followup.send(
            embed=SearchEmbed(self.bot.user, keyword, tracks)
        )

    async def do_shuffle(
        self, interaction: discord.Interaction, ephemeral: bool = False
    ):
        """Helper method to shuffle the queue"""
        logger.info(
            f"Shuffle requested by {interaction.user} in guild {interaction.guild_id}"
        )
        player = await self.ensure_player(interaction)
        player.queue.shuffle()
        await interaction.response.send_message(
            embed=SuccessEmbed(self.bot.user, "Shuffle complete"), ephemeral=ephemeral
        )

    async def do_skip(self, interaction: discord.Interaction, ephemeral: bool = False):
        """Helper method to skip to the next song"""
        logger.info(
            f"Skip requested by {interaction.user} in guild {interaction.guild_id}"
        )
        player = await self.ensure_player(interaction)
        await interaction.response.defer(ephemeral=ephemeral)
        try:
            track = player.queue.peek()
            logger.info(
                f"Skipping to next track: {track.title} in guild {interaction.guild_id}"
            )
            await player.stop()
            embed = SuccessEmbed(
                self.bot.user, f"Skipped to [**{track.title}**]({track.uri})"
            )
            embed.set_thumbnail(url=track.thumbnail)
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        except Empty:
            logger.info(
                f"Skip requested but queue is empty in guild {interaction.guild_id}"
            )
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
        logger.info(
            f"Leave command called by {interaction.user} in guild {interaction.guild_id}"
        )
        player = await self.ensure_player(interaction)
        await player.destroy()
        await interaction.response.send_message(embed=LeaveEmbed(self.bot.user))

    @app_commands.command(name="nowplaying", description="Show the song playing now")
    async def nowplaying(self, interaction: discord.Interaction):
        await interaction.response.defer()
        player = await self.ensure_player(interaction)

        view = NowPlayingView(player)
        await interaction.followup.send(
            view=view
        )

    async def node_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        nodes = get_nodes()
        return [
            app_commands.Choice(
                name=f"{node['identifier']} ({node['nodeName']})",
                value=node["identifier"],
            )
            for node in nodes
        ][:25]

    @app_commands.command(name="switchnode", description="Switch Node")
    @app_commands.autocomplete(node_name=node_autocomplete)
    async def switchnode(
        self,
        interaction: discord.Interaction,
        node_name: str,
    ):
        await interaction.response.defer()
        player = await self.ensure_player(interaction)
        new_node = self.pomice.get_node(identifier=node_name)
        await player.swap_node(new_node)
        await interaction.response.send_message(
            embed=SuccessEmbed(self.bot.user, f"Swapped to {new_node}")
        )

    async def ensure_voice(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client if interaction.guild else None
        if voice_client is None:
            if not interaction.user.voice:
                logger.warning(
                    f"User {interaction.user} not in voice channel in guild {interaction.guild_id}"
                )
                raise commands.CommandError("You are not connected to a voice channel.")
        return voice_client

    async def ensure_player(self, interaction: discord.Interaction) -> CustomPlayer:
        player = interaction.guild.voice_client if interaction.guild else None
        if not player:
            logger.warning(f"Player not found for guild {interaction.guild_id}")
            raise commands.CommandError("The bot is not playing")
        return player

    @commands.Cog.listener("on_pomice_track_end")
    async def on_pomice_track_end(
        self, player: CustomPlayer, track: pomice.Track, reason: str
    ):
        logger.info(
            f"Track ended in guild {player.guild.id}: {track.title} (Reason: {reason})"
        )
        try:
            next_track = player.queue.get()
            if next_track:
                logger.info(
                    f"Playing next track in guild {player.guild.id}: {next_track.title}"
                )
                await player.play(next_track)
            else:
                logger.info(
                    f"Queue empty in guild {player.guild.id}, destroying player"
                )
                await player.destroy()
        except Exception as e:
            logger.error(e)
            await player.destroy()