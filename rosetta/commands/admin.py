import platform
import sys
from datetime import datetime

import discord
import pomice
from discord.ext import commands


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.is_owner()
    @commands.command(name="admin", description="Admin panel with bot statistics")
    async def admin(self, ctx: commands.Context):
        """Display admin panel with comprehensive bot statistics"""

        # Gather bot statistics
        total_guilds = len(self.bot.guilds)
        total_users = sum(guild.member_count for guild in self.bot.guilds)
        total_channels = sum(len(guild.channels) for guild in self.bot.guilds)
        total_voice_channels = sum(
            len(guild.voice_channels) for guild in self.bot.guilds
        )

        # Get bot latency
        latency = round(self.bot.latency * 1000, 2)

        # Version information
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        discord_version = discord.__version__

        # System information
        os_info = f"{platform.system()} {platform.release()}"

        # Shard information
        shard_id = self.bot.shard_id if self.bot.shard_id is not None else 0
        shard_count = self.bot.shard_count if self.bot.shard_count is not None else 1

        # Create embed
        embed = discord.Embed(
            title="🛡️ Admin Panel",
            description="Bot Statistics and Information",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )

        # Bot Statistics
        embed.add_field(
            name="📊 Bot Statistics",
            value=f"**Guilds:** {total_guilds:,}\n"
            f"**Users:** {total_users:,}\n"
            f"**Channels:** {total_channels:,}\n"
            f"**Voice Channels:** {total_voice_channels:,}",
            inline=True,
        )

        # Performance
        embed.add_field(
            name="⚡ Performance",
            value=f"**Latency:** {latency}ms\n**Shard:** {shard_id + 1}/{shard_count}",
            inline=True,
        )

        # Versions
        embed.add_field(
            name="🔧 Versions",
            value=f"**Python:** {python_version}\n**Discord.py:** {discord_version}\n",
            inline=True,
        )

        # System Information
        embed.add_field(
            name="💻 System",
            value=f"**OS:** {os_info}\n**Platform:** {platform.machine()}",
            inline=True,
        )

        # Cog Information
        cog_count = len(self.bot.cogs)
        command_count = len(self.bot.tree.get_commands())
        embed.add_field(
            name="🔌 Loaded Modules",
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
                    status = "🟢 Connected" if node.is_connected else "🔴 Disconnected"
                    latency_ms = round(node.latency * 1000, 2) if node.latency else 0
                    node_info_lines.append(
                        f"**{node._identifier}** {status} • {latency_ms}ms"
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
                    name="🎵 Lavalink Nodes", value="No nodes available", inline=False
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
        embed.set_footer(
            text=f"Requested by {ctx.author.name}",
            icon_url=ctx.author.avatar.url if ctx.author.avatar else None,
        )

        await ctx.send(embed=embed)
