import discord
import os
from dotenv import load_dotenv
load_dotenv()

from commands.basics import Basics
from commands.play import Player

bot = discord.Bot()
TOKEN = os.getenv("TOKEN")

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.register_commands()
    game = discord.Game("Testing")
    await bot.change_presence(status=discord.Status.do_not_disturb, activity=game)

bot.add_cog(Basics(bot))
bot.add_cog(Player(bot))
bot.run(TOKEN)