import discord
from uvicorn import Config, Server
import os
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
    game = discord.Activity(type=discord.ActivityType.competing, name="Testing")
    await bot.change_presence(status=discord.Status.do_not_disturb, activity=game)

    config = Config(app=app)
    server = Server(config)
    
    await server.serve()


bot.add_cog(Basics(bot))
bot.add_cog(Player(bot))

bot.run(TOKEN)