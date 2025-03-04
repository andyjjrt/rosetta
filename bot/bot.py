import discord
from discord.ext import commands
import uvicorn
import os, asyncio
from dotenv import load_dotenv

load_dotenv()

from utils.embeds import ErrorEmbed
from commands.basics import Basics
from commands.play import Player

from api.main import app

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True


bot = discord.Bot(intents=intents)
TOKEN = os.getenv("TOKEN")


@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    game = discord.Activity(type=discord.ActivityType.competing, name="Testing")
    await bot.change_presence(status=discord.Status.do_not_disturb, activity=game)
    
    # config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    # server = uvicorn.Server(config)
    
    # await server.serve()


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

bot.run(TOKEN)