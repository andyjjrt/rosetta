import os
import platform
import sys
from datetime import datetime

import discord
import pomice
from discord import app_commands
from discord.ext import commands

from ..utils.cog import Cog
from ..utils.embeds import PingEmbed
from ..utils.player import CustomPlayer


class Basics(Cog):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot=bot)

    @app_commands.command(name="ping", description="Ping the bot")
    async def ping(self, interaction: discord.Interaction):
        voice_client: CustomPlayer | None = (
            interaction.guild.voice_client if interaction.guild else None
        )
        if voice_client:
            await interaction.response.send_message(
                embed=PingEmbed(self.bot.user, voice_client.node.latency)
            )
        else:
            await interaction.response.send_message(
                embed=PingEmbed(self.bot.user, self.bot.latency)
            )

    @app_commands.command(name="version", description="Show version information")
    async def version(self, interaction: discord.Interaction):
        embed = await self.generate_version_embed(
            interaction, is_admin=await self.bot.is_owner(interaction.user)
        )
        await interaction.response.send_message(embed=embed)

    @commands.is_owner()
    @commands.command(name="version", description="Show version information")
    async def admin(self, ctx: commands.Context):
        embed = await self.generate_version_embed(ctx, is_admin=True)

        await ctx.reply(embed=embed)

    @commands.is_owner()
    @commands.command(name="guilds", description="Show all guilds the bot is in")
    async def guilds(self, ctx: commands.Context):
        """Display all guilds the bot is currently in"""
        from ..utils.views import GuildsView

        view = GuildsView(self.bot)
        await ctx.reply(view=view)

    async def generate_version_embed(
        self, ctx: discord.Interaction | commands.Context, is_admin: bool = False
    ):
        embed = discord.Embed(
            title=":information_source:  Info",
            color=discord.Color.blurple(),
            timestamp=datetime.now(),
        )

        # Gather bot statistics
        total_guilds = len(self.bot.guilds)
        total_users = sum(guild.member_count for guild in self.bot.guilds)
        total_channels = sum(len(guild.channels) for guild in self.bot.guilds)
        total_voice_channels = sum(
            len(guild.voice_channels) for guild in self.bot.guilds
        )

        # Version information
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        discord_version = discord.__version__

        # System information
        os_info = f"{platform.system()} {platform.release()}"

        # Create embed
        embed = discord.Embed(
            title="🛡️ Admin Panel",
            description="Bot Statistics and Information",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )

        # Versions
        embed.add_field(
            name="Version",
            value=os.getenv("ROSETTA_VERSION"),
            inline=True,
        )
        embed.add_field(
            name="Python",
            value=python_version,
            inline=True,
        )
        embed.add_field(
            name="Discord.py",
            value=discord_version,
            inline=True,
        )

        if is_admin:
            # Bot Statistics
            embed.add_field(
                name="Statistics",
                value=f"**Guilds:** {total_guilds:,}\n"
                f"**Users:** {total_users:,}\n"
                f"**Channels:** {total_channels:,}\n"
                f"**Voice Channels:** {total_voice_channels:,}",
                inline=True,
            )

            # System Information
            embed.add_field(
                name="System",
                value=f"**OS:** {os_info}\n**Platform:** {platform.machine()}",
                inline=True,
            )

            # Cog Information
            cog_count = len(self.bot.cogs)
            command_count = len(self.bot.tree.get_commands())
            embed.add_field(
                name="Loaded Modules",
                value=f"**Cogs:** {cog_count}\n**Slash Commands:** {command_count}",
                inline=True,
            )

            # Lavalink Node Information
            try:
                node_pool = pomice.NodePool()
                nodes = node_pool.nodes

                if nodes:
                    node_info_lines = []
                    for node in nodes.values():
                        status = (
                            "🟢 Connected" if node.is_connected else "🔴 Disconnected"
                        )
                        latency_ms = (
                            round(node.latency * 1000, 2) if node.latency else 0
                        )
                        node_info_lines.append(
                            f"- **{node._identifier}** {status} • {latency_ms}ms"
                        )

                    embed.add_field(
                        name=f"🎵 Lavalink Nodes ({len(nodes)})",
                        value="\n".join(node_info_lines)
                        if node_info_lines
                        else "No nodes available",
                        inline=False,
                    )
                else:
                    embed.add_field(
                        name="🎵 Lavalink Nodes",
                        value="No nodes available",
                        inline=False,
                    )
            except Exception as e:
                embed.add_field(
                    name="🎵 Lavalink Nodes",
                    value=f"Error fetching nodes: {str(e)}",
                    inline=False,
                )

        embed.set_thumbnail(
            url=self.bot.user.avatar.url if self.bot.user.avatar else None
        )

        return embed
