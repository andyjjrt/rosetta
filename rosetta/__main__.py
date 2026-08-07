import logging
from inspect import signature
from typing import Protocol

import anyio
import discord
from discord.ext import commands

from rosetta.mcp.runtime import MCPRuntime

from .utils.config import (
    BotConfig,
    CogConfig,
    CogSetting,
    EmojiConfig,
    ManagementSetting,
    MCPConfig,
    McpSetting,
    NanobotConfig,
    NanobotSetting,
    SettingConfig,
)
from .utils.embeds import ErrorEmbed
from .utils.llm_model_access import LlmModelAccessRepository
from .utils.log import LogContext, PydanticAdapter, setup_logging
from .utils.mcp_api_keys import McpApiKeyRepository
from .utils.nanobot_policy import GuildPolicyRepository
from .utils.settings_store import SettingsDatabase

setup_logging(dev_mode=BotConfig.DEBUG)
logger = logging.getLogger("rosetta")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True


class ClosableNanobotCog(Protocol):
    async def aclose(self) -> None: ...


class RosettaBot(commands.Bot):
    def __init__(
        self,
        *,
        cog_config: CogSetting = CogConfig,
        mcp_config: McpSetting = MCPConfig,
        nanobot_config: NanobotSetting = NanobotConfig,
        setting_config: ManagementSetting = SettingConfig,
    ) -> None:
        super().__init__(command_prefix="!", intents=intents)
        self._cog_config = cog_config
        self._mcp_config = mcp_config
        self._nanobot_config = nanobot_config
        self._setting_config = setting_config
        self._settings_database: SettingsDatabase | None = None
        self._llm_model_access_repository: LlmModelAccessRepository | None = None
        self._mcp_api_key_repository: McpApiKeyRepository | None = None
        self._nanobot_policy_repository: GuildPolicyRepository | None = None
        self._mcp_runtime: MCPRuntime | None = None
        self._nanobot_cog: ClosableNanobotCog | None = None

    async def setup_hook(self) -> None:
        if not self._cog_config.NANOBOT_DISABLE and self._cog_config.MUSIC_DISABLE:
            raise RuntimeError(
                "COG_NANOBOT_DISABLE=false requires COG_MUSIC_DISABLE=false"
            )
        if not self._cog_config.NANOBOT_DISABLE and not self._mcp_config.ENABLED:
            raise RuntimeError("COG_NANOBOT_DISABLE=false requires MCP_ENABLED=true")
        if self._mcp_config.ENABLED and self._cog_config.MUSIC_DISABLE:
            raise RuntimeError("MCP_ENABLED requires COG_MUSIC_DISABLE=false")
        self._nanobot_config.validate_startup(self._cog_config)

        self._settings_database = SettingsDatabase(self._setting_config.DATABASE_PATH)
        self._llm_model_access_repository = LlmModelAccessRepository(
            self._setting_config.DATABASE_PATH
        )
        self._mcp_api_key_repository = McpApiKeyRepository(
            self._setting_config.DATABASE_PATH
        )
        self._nanobot_policy_repository = GuildPolicyRepository(
            self._nanobot_config.POLICY_PATH
        )

        if not self._cog_config.BASICS_DISABLE:
            from .commands.basics import Basics

            await self.add_cog(Basics(self))
        from .commands.settings import Setting

        await self.add_cog(
            Setting(
                self,
                mcp_api_key_repository=self._mcp_api_key_repository,
                model_access_repository=self._llm_model_access_repository,
                nanobot_policy_repository=self._nanobot_policy_repository,
            )
        )
        mcp_started_by_this_setup = False
        if not self._cog_config.MUSIC_DISABLE:
            from .commands.music import Music

            music = Music(self)
            await self.add_cog(music)
            if self._mcp_config.ENABLED:
                if self._mcp_runtime is None:
                    self._mcp_runtime = self._create_mcp_runtime(music.service)
                    await self._mcp_runtime.start()
                    mcp_started_by_this_setup = True
        if not self._cog_config.NANOBOT_DISABLE:
            await self._setup_nanobot(
                mcp_started_by_this_setup=mcp_started_by_this_setup
            )
        if not self._cog_config.MYGO_DISABLE:
            from .commands.mygo import Mygo

            await self.add_cog(Mygo(self))
        if not self._cog_config.LLM_DISABLE:
            from .commands.llm import LLM

            await self.add_cog(
                LLM(
                    self,
                    model_access_repository=self._llm_model_access_repository,
                )
            )

    async def _setup_nanobot(self, *, mcp_started_by_this_setup: bool) -> None:
        from .commands.nanobot import Nanobot
        from .utils.nanobot_client import NanobotSdkClient

        client = None
        cog = None
        added = False
        try:
            client = NanobotSdkClient.create(self._nanobot_config)
            cog = Nanobot(
                self,
                policy_repository=self._nanobot_policy_repository,
                client=client,
            )
            await self.add_cog(cog)
            added = True
            self._nanobot_cog = cog
        except BaseException as error:  # noqa: BLE001  # BROAD_EXCEPT_OK: composition boundary re-raises after cleanup.
            await self._rollback_nanobot_startup(
                error,
                partial_client=client,
                partial_cog=cog,
                cog_added=added,
                stop_owned_mcp=mcp_started_by_this_setup,
            )
            raise

    def _create_mcp_runtime(self, music_service) -> MCPRuntime:
        if "api_key_validator" not in signature(MCPRuntime).parameters:
            return MCPRuntime(self._mcp_config, music_service)
        return MCPRuntime(
            self._mcp_config,
            music_service,
            api_key_validator=self._mcp_api_key_repository,
        )

    async def _rollback_nanobot_startup(
        self,
        original: BaseException,
        *,
        partial_client,
        partial_cog: ClosableNanobotCog | None,
        cog_added: bool,
        stop_owned_mcp: bool,
    ) -> None:
        self._nanobot_cog = None
        if cog_added and partial_cog is not None:
            self.remove_cog(getattr(partial_cog, "qualified_name", "Nanobot"))
        if partial_cog is not None:
            await self._cleanup_step(original, partial_cog.aclose)
        elif partial_client is not None:
            await self._cleanup_step(original, partial_client.aclose)
        if stop_owned_mcp and self._mcp_runtime is not None:
            runtime = self._mcp_runtime
            self._mcp_runtime = None
            await self._cleanup_step(original, runtime.stop)

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
        failure: BaseException | None = None
        nanobot_cog = self._nanobot_cog
        self._nanobot_cog = None
        if nanobot_cog is not None:
            failure = await self._close_collecting(failure, nanobot_cog.aclose)

        runtime = self._mcp_runtime
        self._mcp_runtime = None
        if runtime is not None:
            failure = await self._close_collecting(failure, runtime.stop)

        failure = await self._close_collecting(failure, super().close)
        if failure is not None:
            raise failure

    async def _close_collecting(self, failure: BaseException | None, close_call):
        try:
            with anyio.CancelScope(shield=True):
                await close_call()
        except BaseException as error:  # noqa: BLE001  # BROAD_EXCEPT_OK: cleanup must continue, then re-raise.
            if failure is None:
                return error
            failure.add_note(f"suppressed cleanup error: {error}")
        return failure

    async def _cleanup_step(self, original: BaseException, close_call) -> None:
        try:
            with anyio.CancelScope(shield=True):
                await close_call()
        except BaseException as error:  # noqa: BLE001  # BROAD_EXCEPT_OK: rollback preserves original failure.
            original.add_note(f"suppressed rollback cleanup error: {error}")


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
