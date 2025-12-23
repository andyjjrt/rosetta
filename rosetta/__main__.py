import logging
import os
from pathlib import Path

import discord
from discord.ext import commands

from .commands import LLM, Basics, Mygo, Music
from .utils import setup_logging
from .utils.config import EMOJI, TOKEN
from .utils.embeds import ErrorEmbed

setup_logging(Path(__file__).resolve().parent / "logging.yaml")
logger = logging.getLogger("rosetta")

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True

pod_name = os.environ.get("SHARD_ID", "rosetta-0")
shard_id = int(pod_name.split("-")[-1])
total_shards = int(os.environ.get("TOTAL_SHARDS", 1))

bot = commands.Bot(
    command_prefix="!", intents=intents, shard_id=shard_id, shard_count=total_shards
)


@bot.event
async def on_ready():
    logger.info(f"We have logged in as {bot.user}")
    
    # Fetch and store application emojis
    try:
        app_emojis = await bot.fetch_application_emojis()
        emoji_dict = {emoji.name: str(emoji) for emoji in app_emojis}
        EMOJI.set_emojis(emoji_dict)
        logger.info(f"Loaded {len(emoji_dict)} application emoji(s)")
    except Exception as e:
        logger.error(f"Failed to fetch application emojis: {e}")
    
    status = discord.Activity(type=discord.ActivityType.listening, name="/play")
    await bot.change_presence(status=discord.Status.online, activity=status)
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
):
    logger.error(error)
    
    # Determine the error message
    if isinstance(error, discord.app_commands.CommandInvokeError):
        original_error = error.original
        if isinstance(original_error, commands.CommandError):
            error_embed = ErrorEmbed(bot.user, f"[Command] {original_error}")
        else:
            error_embed = ErrorEmbed(bot.user, f"[Error] {original_error}")
    else:
        error_embed = ErrorEmbed(bot.user, f"[Unknown] {error}")
    
    # Send the error message using the appropriate method
    try:
        if interaction.response.is_done():
            # Interaction already responded to, use followup
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        else:
            # Interaction not yet responded to, use response
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
    except discord.errors.InteractionResponded:
        # Fallback in case the check above didn't catch it
        await interaction.followup.send(embed=error_embed, ephemeral=True)


async def setup_hook():
    await bot.add_cog(Basics(bot))
    await bot.add_cog(Music(bot))
    await bot.add_cog(Mygo(bot))
    await bot.add_cog(LLM(bot))


bot.setup_hook = setup_hook

logger.info("Starting the application...")
bot.run(TOKEN)
