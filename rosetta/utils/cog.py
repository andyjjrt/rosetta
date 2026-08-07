import logging
import time

import discord
from discord.ext import commands

from .log import LogContext, PydanticAdapter


class Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._logger = logging.getLogger("rosetta")

    async def interaction_setup(self, interaction: discord.Interaction) -> bool:
        if interaction.type == discord.InteractionType.application_command:
            interaction.extras["start_time"] = time.perf_counter()

            ctx_data = LogContext.from_interaction(interaction)
            adapter = PydanticAdapter(self._logger, ctx_data)
            interaction.extras["logger"] = adapter

            adapter.info(f"Command '{ctx_data.command}' invoked")

        return True

    async def cog_load(self):
        self.bot.tree.interaction_check = self.interaction_setup
        self._logger.info(f"{self.__class__.__name__} loaded")

    async def cog_unload(self):
        self.bot.tree.interaction_check = None
