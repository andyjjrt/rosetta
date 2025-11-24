import os

import discord
from discord import app_commands
from discord.ext import commands
from yt_dlp.version import __version__

from ..utils.embeds import InfoEmbed, PingEmbed


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
