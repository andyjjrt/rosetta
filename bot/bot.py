import discord
from uvicorn import Config, Server
import requests, os, sys, asyncio
from dotenv import load_dotenv

load_dotenv()

from commands.basics import Basics
from commands.play import Player

from api.main import app

bot = discord.Bot()
TOKEN = os.getenv("TOKEN")


@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.register_commands()
    game = discord.Game("Testing")
    await bot.change_presence(status=discord.Status.do_not_disturb, activity=game)

    loop = asyncio.new_event_loop()
    config = Config(app=app, loop=loop)
    server = Server(config)

    loop.run_until_complete(await server.serve())


bot.add_cog(Basics(bot))
bot.add_cog(Player(bot))

bot.run(TOKEN)
