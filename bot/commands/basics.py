from discord import Bot, ApplicationContext
from discord.ext import commands
from utils.embeds import PingEmbed
import os

class Basics(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.slash_command()
    async def ping(self, ctx: ApplicationContext):
        if ctx.voice_client:
            await ctx.respond(embed=PingEmbed(self.bot, ctx.voice_client.latency))
        else:
            await ctx.respond(embed=PingEmbed(self.bot, self.bot.latency))
