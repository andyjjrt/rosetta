import os

from discord import ApplicationContext, Bot
from discord.ext import commands
from yt_dlp.version import __version__

from ..utils.embeds import InfoEmbed, PingEmbed


class Basics(commands.Cog):
    __cog_name__ = "Basics"

    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.slash_command(description="Ping the bot")
    async def ping(self, ctx: ApplicationContext):
        if ctx.voice_client:
            await ctx.respond(embed=PingEmbed(self.bot.user, ctx.voice_client.latency))
        else:
            await ctx.respond(embed=PingEmbed(self.bot.user, self.bot.latency))

    @commands.slash_command()
    async def version(self, ctx: ApplicationContext):
        embed = InfoEmbed(self.bot.user, "")
        embed.add_field(name="version", value=os.getenv("ROSETTA_VERSION"))
        embed.add_field(name="yt-dlp version", value=__version__)
        await ctx.respond(embed=embed)
