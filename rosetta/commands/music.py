import asyncio
import logging
from functools import partial

import discord
import pomice
from discord import app_commands
from discord.ext import commands

from ..utils.cog import Cog
from ..utils.config import LavalinkConfig
from ..utils.embeds import (
    LeaveEmbed,
    ProcessingEmbed,
    SuccessEmbed,
)
from ..utils.player import CustomPlayer, LoopMode
from ..utils.views import NowPlayingView, SearchView


def get_k8s_lavalink_endpoints() -> list[dict]:
    """
    Discover Lavalink nodes from Kubernetes Endpoints.
    Returns a list of dicts with host, port, password, and identifier.
    """
    try:
        from kubernetes import client
        from kubernetes import config as k8s_config

        logger = logging.getLogger("rosetta")

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
                        node_name = address.node_name
                        if address.target_ref:
                            node_id = address.target_ref.name
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
        },
        {
            "host": LavalinkConfig.HOST,
            "port": LavalinkConfig.PORT + 1,
            "password": LavalinkConfig.PASSWORD,
            "identifier": "MAIN2",
            "nodeName": "localhost",
        },
    ]


def get_nodes() -> list[dict]:
    if LavalinkConfig.DISCOVERY_MODE == "k8s":
        nodes = get_k8s_lavalink_endpoints()
        if not nodes:
            nodes = get_local_lavalink_endpoints()
    else:
        nodes = get_local_lavalink_endpoints()
    return nodes


class Music(Cog):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.pomice = pomice.NodePool()
        asyncio.create_task(self.start_nodes())

    @commands.command(name="reload_nodes")
    @commands.is_owner()
    async def reload_nodes(self, ctx: commands.Context):
        """Reload Lavalink nodes by removing all and re-registering. (Owner only)"""
        self._logger.info("Reloading Lavalink nodes...")
        await ctx.send("🔄 Reloading Lavalink nodes...")

        # Remove all existing nodes
        for node_name, node in self.pomice.nodes.items():
            try:
                await node.disconnect()
                self._logger.info(f"Removed Lavalink node '{node_name}'")
            except Exception as e:
                self._logger.error(f"Failed to remove node '{node_name}': {e}")

        # Re-register nodes
        await self.start_nodes()

        await ctx.send(f"✅ Node reload complete. Total nodes: {len(self.pomice.nodes)}")

    async def start_nodes(self):
        """
        Start Pomice nodes based on discovery mode.
        - "k8s": Auto-discover Lavalink nodes from Kubernetes Endpoints
        - "local": Use local configuration from environment variables
        """
        self._logger.info(
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
                self._logger.info(
                    f"Pomice node '{node['identifier']}' is ready at {node['host']}:{node['port']}"
                )
            except Exception as e:
                self._logger.error(f"Failed to create node '{node['identifier']}': {e}")

        if not self.pomice.nodes:
            self._logger.error("No Lavalink nodes available!")

    async def remove_nodes(self):
        await self.pomice.disconnect()

    async def node_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        nodes = get_nodes()
        return [
            app_commands.Choice(
                name=f"{node['identifier']} ({node['nodeName']})",
                value=node["identifier"],
            )
            for node in nodes
        ][:25]

    async def _play(
        self,
        interaction: discord.Interaction,
        url: str,
        loop: str = "Off",
        shuffle: bool = False,
        top: bool = False,
        node_name: str | None = None,
    ):
        adapter = interaction.extras.get("logger")
        player: CustomPlayer | None = (
            interaction.guild.voice_client if interaction.guild else None
        )
        if player is None:
            if interaction.user.voice and interaction.user.voice.channel:
                player_cls = (
                    partial(CustomPlayer, node_identifier=node_name)
                    if node_name
                    else CustomPlayer
                )
                player: CustomPlayer = await interaction.user.voice.channel.connect(
                    cls=player_cls
                )
                await player.set_volume(10)

        results = await player.get_tracks(
            query=f"{url}", search_type=pomice.URLRegex.YOUTUBE_URL
        )

        if not results:
            adapter.error(f"No results found for search term: {url}")
            raise commands.CommandError("No results were found for that search term.")

        if isinstance(results, pomice.Playlist):
            tracks = results.tracks
            name = results.name
            uri = results.uri
            thumbnail = results.thumbnail
            adapter.info(f"Enqueued playlist: {name} ({len(tracks)} tracks)")
        else:
            tracks = results
            name = tracks[0].title
            uri = tracks[0].uri
            thumbnail = tracks[0].thumbnail
            adapter.info(f"Enqueued track: {name}")

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

        embed = SuccessEmbed(
            interaction.user,
            f"Enqueued [**{name}**]({uri})",
        )
        embed.set_footer(
            text=f"{interaction.user.name} • {player.node._identifier}",
            icon_url=interaction.user.avatar,
        )
        embed.set_thumbnail(url=thumbnail)

        return embed

    @app_commands.command(name="play", description="Play Youtube music")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
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
    @app_commands.autocomplete(node_name=node_autocomplete)
    async def play(
        self,
        interaction: discord.Interaction,
        url: str,
        loop: str = "Off",
        shuffle: bool = False,
        top: bool = False,
        node_name: str | None = None,
    ):
        await self.ensure_voice(interaction)
        await interaction.response.defer()
        message = await interaction.followup.send(
            embed=ProcessingEmbed(self.bot.user), wait=True
        )
        embed = await self._play(interaction, url, loop, shuffle, top, node_name)
        await message.edit(embed=embed)

    @app_commands.command(name="loop", description="Set loop")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(loop="loop mode")
    @app_commands.choices(
        loop=[
            app_commands.Choice(name="Off", value="Off"),
            app_commands.Choice(name="One", value="One"),
            app_commands.Choice(name="Queue", value="Queue"),
        ]
    )
    async def loop_command(self, interaction: discord.Interaction, loop: str = "Off"):
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
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(keyword="keyword")
    async def search(self, interaction: discord.Interaction, keyword: str):
        adapter = interaction.extras.get("logger")
        await interaction.response.defer()
        tracks = await self.pomice.get_node().get_tracks(keyword)
        adapter.info(f"Searched with keyword: {keyword}")
        view = SearchView(self.bot, keyword, tracks)
        await interaction.followup.send(view=view)

    async def do_shuffle(
        self, interaction: discord.Interaction, ephemeral: bool = False
    ):
        """Helper method to shuffle the queue"""
        player = await self.ensure_player(interaction)
        player.queue.shuffle()
        await interaction.response.send_message(
            embed=SuccessEmbed(self.bot.user, "Shuffle complete"), ephemeral=ephemeral
        )

    async def do_skip(self, interaction: discord.Interaction, ephemeral: bool = False):
        """Helper method to skip to the next song"""
        adapter = interaction.extras.get("logger")
        player = await self.ensure_player(interaction)
        await interaction.response.defer(ephemeral=ephemeral)
        track = player.queue.get()
        if track:
            adapter.info(f"Skipped to next track: {track.title}")
            await player.play(track)
            embed = SuccessEmbed(
                self.bot.user, f"Skipped to [**{track.title}**]({track.uri})"
            )
            embed.set_thumbnail(url=track.thumbnail)
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            adapter.info("Skip requested but queue is empty")
            await player.destroy()
            await interaction.followup.send(
                embed=SuccessEmbed(self.bot.user, "No song left, leaving")
            )

    @app_commands.command(name="shuffle", description="Shuffle")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(ephemeral="hide response")
    async def shuffle(self, interaction: discord.Interaction, ephemeral: bool = False):
        await self.do_shuffle(interaction, ephemeral)

    @app_commands.command(name="skip", description="Skip to next song")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(ephemeral="hide response")
    async def skip(self, interaction: discord.Interaction, ephemeral: bool = False):
        await self.do_skip(interaction, ephemeral)

    @app_commands.command(name="leave", description="Leave current channel")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def leave(self, interaction: discord.Interaction):
        player = await self.ensure_player(interaction)
        await player.destroy()
        await interaction.response.send_message(embed=LeaveEmbed(self.bot.user))

    @app_commands.command(name="nowplaying", description="Show the song playing now")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def nowplaying(self, interaction: discord.Interaction):
        await interaction.response.defer()
        player = await self.ensure_player(interaction)

        view = NowPlayingView(player, interaction.user)
        await interaction.followup.send(view=view)

    @app_commands.command(name="switchnode", description="Switch to a different Lavalink node")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.describe(node_name="The node to switch to")
    @app_commands.autocomplete(node_name=node_autocomplete)
    async def switchnode(
        self,
        interaction: discord.Interaction,
        node_name: str,
    ):
        adapter = interaction.extras.get("logger")
        await interaction.response.defer()
        player = await self.ensure_player(interaction)
        
        old_node_id = player.node._identifier
        new_node = self.pomice.get_node(identifier=node_name)
        
        if new_node is None:
            raise commands.CommandError(f"Node '{node_name}' not found")
        
        if old_node_id == node_name:
            await interaction.followup.send(
                embed=SuccessEmbed(self.bot.user, f"Already connected to **{node_name}**")
            )
            return
        
        await player.swap_node(new_node)
        adapter.info(f"Switched from node '{old_node_id}' to '{node_name}'")
        
        await interaction.followup.send(
            embed=SuccessEmbed(self.bot.user, f"Switched from **{old_node_id}** to **{node_name}**")
        )

    async def ensure_voice(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client if interaction.guild else None
        adapter = interaction.extras.get("logger")
        if voice_client is None:
            if not interaction.user.voice:
                adapter.warning(
                    f"User {interaction.user} not in voice channel in guild {interaction.guild.name}"
                )
                raise commands.CommandError("You are not connected to a voice channel.")
        return voice_client

    async def ensure_player(self, interaction: discord.Interaction) -> CustomPlayer:
        player = interaction.guild.voice_client if interaction.guild else None
        adapter = interaction.extras.get("logger")
        if not player:
            adapter.warning(f"Player not found for guild {interaction.guild.name}")
            raise commands.CommandError("The bot is not playing")
        return player

    @commands.Cog.listener("on_pomice_track_end")
    async def on_pomice_track_end(
        self, player: CustomPlayer, track: pomice.Track, reason: str
    ):
        self._logger.info(
            f"Track {track} ended in guild {player.guild.name} (Reason: {reason})"
        )
        if reason == "finished":
            try:
                next_track = player.queue.get()
                if next_track:
                    self._logger.info(
                        f"Playing next track in guild {player.guild.name}: {next_track.title}"
                    )
                    await player.play(next_track)
                else:
                    self._logger.info(
                        f"Queue empty in guild {player.guild.name}, destroying player"
                    )
                    await player.destroy()
            except Exception as e:
                self._logger.error(e)
                await player.destroy()
