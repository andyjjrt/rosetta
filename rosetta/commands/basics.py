import os

import discord
from discord import app_commands
from discord.ext import commands
from yt_dlp.version import __version__

from ..utils.embeds import ErrorEmbed, InfoEmbed, PingEmbed, SuccessEmbed


class Basics(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Ping the bot")
    async def ping(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client if interaction.guild else None
        if voice_client:
            await interaction.response.send_message(
                embed=PingEmbed(self.bot.user, voice_client.latency)
            )
        else:
            await interaction.response.send_message(
                embed=PingEmbed(self.bot.user, self.bot.latency)
            )

    @app_commands.command(name="version", description="Show version information")
    async def version(self, interaction: discord.Interaction):
        embed = InfoEmbed(self.bot.user, "")
        embed.add_field(name="version", value=os.getenv("ROSETTA_VERSION"))
        embed.add_field(name="yt-dlp version", value=__version__)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="servers", description="[Owner] Show servers the bot is in")
    async def servers(self, interaction: discord.Interaction):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message(
                embed=ErrorEmbed(self.bot.user, "This command is owner-only."),
                ephemeral=True,
            )
            return

        guilds = self.bot.guilds
        guild_list = "\n".join(
            [f"- **{guild.name}** (`{guild.id}`) - {guild.member_count} members" for guild in guilds[:20]]
        )
        if len(guilds) > 20:
            guild_list += f"\n... and {len(guilds) - 20} more"

        embed = InfoEmbed(
            self.bot.user,
            f"**Total servers:** {len(guilds)}\n\n{guild_list}",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="leave-server", description="[Owner] Leave a server by ID")
    @app_commands.describe(server_id="The ID of the server to leave")
    async def leave_server(self, interaction: discord.Interaction, server_id: str):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message(
                embed=ErrorEmbed(self.bot.user, "This command is owner-only."),
                ephemeral=True,
            )
            return

        try:
            guild_id = int(server_id)
        except ValueError:
            await interaction.response.send_message(
                embed=ErrorEmbed(self.bot.user, "Invalid server ID."),
                ephemeral=True,
            )
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            await interaction.response.send_message(
                embed=ErrorEmbed(self.bot.user, f"Bot is not in a server with ID `{server_id}`."),
                ephemeral=True,
            )
            return

        guild_name = guild.name
        await guild.leave()
        await interaction.response.send_message(
            embed=SuccessEmbed(self.bot.user, f"Left server **{guild_name}** (`{server_id}`)."),
            ephemeral=True,
        )
