import logging

import discord
from discord.ext import commands

from .commands import LLM, Basics, Music, Mygo
from .utils.config import BotConfig, EmojiConfig
from .utils.embeds import ErrorEmbed
from .utils.log import LogContext, PydanticAdapter, setup_logging

setup_logging(dev_mode=BotConfig.DEBUG)
logger = logging.getLogger("rosetta")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    logger.info(f"We have logged in as {bot.user}")

    # Fetch and store application emojis
    try:
        app_emojis = await bot.fetch_application_emojis()
        emoji_dict = {emoji.name: str(emoji) for emoji in app_emojis}
        EmojiConfig.set_emojis(emoji_dict)
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
    ctx_data = LogContext.from_interaction(interaction)
    adapter = PydanticAdapter(logger, ctx_data)

    adapter.error(error)
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
bot.run(BotConfig.TOKEN)
