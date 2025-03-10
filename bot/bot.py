import discord
from discord.ext import commands
import logging, asyncio, configparser

from utils.embeds import ErrorEmbed
from commands.basics import Basics
from commands.play import Player
from commands.mygo import Mygo

from api.main import app

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True

config = configparser.ConfigParser()
config.read("../config.ini")

bot = discord.Bot(intents=intents)
TOKEN = config["bot"].get("TOKEN")

logger = logging.getLogger('uvicorn.error')

@bot.event
async def on_ready():
    logger.info(f"We have logged in as {bot.user}")
    game = discord.Activity(type=discord.ActivityType.competing, name="Testing")
    await bot.change_presence(status=discord.Status.do_not_disturb, activity=game)


@bot.event
async def on_application_command_error(
    ctx: discord.ApplicationContext, error: discord.DiscordException
):
    print(error)
    if isinstance(error, commands.CommandError):
        await ctx.respond(embed=ErrorEmbed(bot.user, f"[Command] {error}"))
    else:
        await ctx.respond(embed=ErrorEmbed(bot.user, f"[Unknown] {error}"))
        raise error


bot.add_cog(Basics(bot))
bot.add_cog(Player(bot))
bot.add_cog(Mygo(bot))


async def run():
    try:
        await bot.start(TOKEN)
    except KeyboardInterrupt:
        pass


asyncio.create_task(run())
