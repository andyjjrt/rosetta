from discord import Bot, ApplicationContext
from discord.ext import commands
from utils.embeds import PingEmbed, InfoEmbed
import os


class Basics(commands.Cog):
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
        await ctx.respond(embed=InfoEmbed(self.bot.user, os.getenv("ROSETTA_VERSION")))
