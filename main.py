import discord
from discord.ext import commands
import logging
import asyncio

from langfuse import Langfuse

from utils.config import TOKEN
from utils.embeds import ErrorEmbed
from commands.basics import Basics
from commands.play import Player
from commands.mygo import Mygo
from commands.chat import LLM

from api.main import app  # noqa: F401


intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True

bot = discord.Bot(intents=intents)

logger = logging.getLogger("uvicorn.error")

@bot.event
async def on_ready():
    await bot.sync_commands()
    logger.info(f"We have logged in as {bot.user}")
    status = discord.Activity(type=discord.ActivityType.listening, name="/play")
    await bot.change_presence(status=discord.Status.online, activity=status)


@bot.event
async def on_application_command_error(
    ctx: discord.ApplicationContext, error: discord.DiscordException
):
    logging.error(error)
    if isinstance(error, commands.CommandError):
        await ctx.respond(embed=ErrorEmbed(bot.user, f"[Command] {error}"))
    else:
        await ctx.respond(embed=ErrorEmbed(bot.user, f"[Unknown] {error}"))
        raise error


@bot.event
async def on_application_command(ctx: discord.ApplicationContext):
    # logger.info(f"{ctx.author} uses {ctx.interaction.data} {ctx.channel} {ctx.guild}")
    logger.info(f"[{ctx.channel}] {ctx.author} uses /{ctx.command}")


bot.add_cog(Basics(bot))
bot.add_cog(Player(bot))
bot.add_cog(Mygo(bot))
bot.add_cog(LLM(bot))


async def run():
    try:
        await bot.start(TOKEN)
    except KeyboardInterrupt:
        pass


asyncio.create_task(run())
