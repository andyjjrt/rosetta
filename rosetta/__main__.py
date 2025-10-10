import logging
from pathlib import Path

import discord
from discord.ext import commands

from .commands import LLM, Basics, Mygo, Player
from .utils import setup_logging
from .utils.config import TOKEN
from .utils.embeds import ErrorEmbed

setup_logging(Path(__file__).resolve().parent / "logging.yaml")
logger = logging.getLogger("rosetta")

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True

bot = discord.Bot(intents=intents)


@bot.event
async def on_ready():
    logger.info(f"We have logged in as {bot.user}")
    status = discord.Activity(type=discord.ActivityType.listening, name="/play")
    await bot.change_presence(status=discord.Status.online, activity=status)


@bot.event
async def on_application_command_error(
    ctx: discord.ApplicationContext, error: discord.DiscordException
):
    logger.error(error)
    if isinstance(error, commands.CommandError):
        await ctx.respond(embed=ErrorEmbed(bot.user, f"[Command] {error}"))
    else:
        await ctx.respond(embed=ErrorEmbed(bot.user, f"[Unknown] {error}"))


@bot.event
async def on_application_command(ctx: discord.ApplicationContext):
    # logger.info(f"{ctx.author} uses {ctx.interaction.data} {ctx.channel} {ctx.guild}")
    logger.info(
        f"[{ctx.channel}] {ctx.author} uses /{ctx.command}", extra={"markup": False}
    )


bot.add_cog(Basics(bot))
bot.add_cog(Player(bot))
bot.add_cog(Mygo(bot))
bot.add_cog(LLM(bot))


logger.info("Starting the application...")
bot.run(TOKEN)
