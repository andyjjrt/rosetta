import logging

import discord
from discord.ext import commands

from rosetta.mcp.runtime import MCPRuntime

from .utils.config import (
    BotConfig,
    CogConfig,
    CogSetting,
    EmojiConfig,
    MCPConfig,
    McpSetting,
)
from .utils.embeds import ErrorEmbed
from .utils.log import LogContext, PydanticAdapter, setup_logging

setup_logging(dev_mode=BotConfig.DEBUG)
logger = logging.getLogger("rosetta")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True


class RosettaBot(commands.Bot):
    def __init__(
        self,
        *,
        cog_config: CogSetting = CogConfig,
        mcp_config: McpSetting = MCPConfig,
    ) -> None:
        super().__init__(command_prefix="!", intents=intents)
        self._cog_config = cog_config
        self._mcp_config = mcp_config
        self._mcp_runtime: MCPRuntime | None = None

    async def setup_hook(self) -> None:
        if self._mcp_config.ENABLED and self._cog_config.MUSIC_DISABLE:
            raise RuntimeError("MCP_ENABLED requires COG_MUSIC_DISABLE=false")

        if not self._cog_config.BASICS_DISABLE:
            from .commands.basics import Basics

            await self.add_cog(Basics(self))
        if not self._cog_config.MUSIC_DISABLE:
            from .commands.music import Music

            music = Music(self)
            await self.add_cog(music)
            if self._mcp_config.ENABLED:
                self._mcp_runtime = MCPRuntime(self._mcp_config, music.service)
                await self._mcp_runtime.start()
        if not self._cog_config.MYGO_DISABLE:
            from .commands.mygo import Mygo

            await self.add_cog(Mygo(self))
        if not self._cog_config.LLM_DISABLE:
            from .commands.llm import LLM

            await self.add_cog(LLM(self))

    async def on_ready(self) -> None:
        logger.info(f"We have logged in as {self.user}")

        try:
            app_emojis = await self.fetch_application_emojis()
            emoji_dict = {emoji.name: str(emoji) for emoji in app_emojis}
            EmojiConfig.set_emojis(emoji_dict)
            logger.info(f"Loaded {len(emoji_dict)} application emoji(s)")
        except discord.HTTPException as e:
            logger.error(f"Failed to fetch application emojis: {e}")

        status = discord.Activity(type=discord.ActivityType.listening, name="/play")
        await self.change_presence(status=discord.Status.online, activity=status)
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except (discord.HTTPException, discord.app_commands.CommandSyncFailure) as e:
            logger.error(f"Failed to sync commands: {e}")

    async def close(self) -> None:
        try:
            if self._mcp_runtime is not None:
                await self._mcp_runtime.stop()
        finally:
            await super().close()


bot = RosettaBot()


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
) -> None:
    ctx_data = LogContext.from_interaction(interaction)
    adapter = PydanticAdapter(logger, ctx_data)

    adapter.error(error)
    if isinstance(error, discord.app_commands.CommandInvokeError):
        original_error = error.original
        if isinstance(original_error, commands.CommandError):
            error_embed = ErrorEmbed(bot.user, f"[Command] {original_error}")
        else:
            error_embed = ErrorEmbed(bot.user, f"[Error] {original_error}")
    else:
        error_embed = ErrorEmbed(bot.user, f"[Unknown] {error}")

    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
    except discord.errors.InteractionResponded:
        await interaction.followup.send(embed=error_embed, ephemeral=True)


def main() -> None:
    logger.info("Starting the application...")
    bot.run(BotConfig.TOKEN)


if __name__ == "__main__":
    main()
