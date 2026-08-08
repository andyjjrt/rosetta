from __future__ import annotations

from typing import Final

import discord
from discord import app_commands
from discord.ext import commands

from rosetta.utils.cog import Cog
from rosetta.utils.config import NanobotConfig, SettingConfig
from rosetta.utils.llm_model_access import (
    LlmModelAccessAlreadyGranted,
    LlmModelAccessNotFound,
    LlmModelAccessRepository,
)
from rosetta.utils.mcp_api_keys import (
    ApiKeyNameAlreadyExists,
    ApiKeyNotFound,
    McpApiKeyRepository,
)
from rosetta.utils.nanobot_policy import GuildId, GuildPolicyRepository
from rosetta.utils.views.Nanobot import NanobotPolicyStore, NanobotSettingsView

from .setting_support import (
    build_llm_access_list_view,
    build_mcp_key_list_view,
    ensure_owner,
    ensure_valid_mcp_key_name,
    parse_user_id,
)

_GUILD_REQUIRED_MESSAGE: Final = "Nanobot settings are only available in a server."


class Setting(Cog):
    setting_group = app_commands.Group(
        name="setting",
        description="Owner-only Rosetta settings",
    )
    mcp_group = app_commands.Group(
        name="mcp",
        description="Manage MCP API keys",
        parent=setting_group,
    )
    llm_group = app_commands.Group(
        name="llm",
        description="Manage LLM model selection access",
        parent=setting_group,
    )

    def __init__(
        self,
        bot: commands.Bot,
        *,
        mcp_api_key_repository: McpApiKeyRepository | None = None,
        model_access_repository: LlmModelAccessRepository | None = None,
        nanobot_policy_repository: NanobotPolicyStore | None = None,
    ) -> None:
        super().__init__(bot)
        self._mcp_api_key_repository = mcp_api_key_repository or McpApiKeyRepository(
            SettingConfig.DATABASE_PATH
        )
        self._model_access_repository = (
            model_access_repository
            or LlmModelAccessRepository(SettingConfig.DATABASE_PATH)
        )
        self._nanobot_policy_repository = (
            nanobot_policy_repository
            or GuildPolicyRepository(NanobotConfig.POLICY_PATH)
        )

    @mcp_group.command(name="create", description="Create an MCP API key")
    @app_commands.describe(
        name="Key name: 1-64 letters, numbers, hyphens, or underscores"
    )
    async def create_mcp_key(self, interaction: discord.Interaction, name: str) -> None:
        if not await ensure_owner(interaction):
            return
        if not await ensure_valid_mcp_key_name(interaction, name):
            return

        try:
            created = await self._mcp_api_key_repository.create(name)
        except ApiKeyNameAlreadyExists:
            await interaction.response.send_message(
                f"MCP API key `{name}` already exists.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Created MCP API key "
            f"`{created.name}`. Copy it now; it will not be shown again.\n"
            f"Plaintext key: `{created.plaintext_key}`",
            ephemeral=True,
        )

    @mcp_group.command(name="list", description="List MCP API keys")
    async def list_mcp_keys(self, interaction: discord.Interaction) -> None:
        if not await ensure_owner(interaction):
            return

        keys = await self._mcp_api_key_repository.list()
        view = build_mcp_key_list_view(keys)
        await interaction.response.send_message(
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @mcp_group.command(name="rotate", description="Rotate an MCP API key")
    @app_commands.describe(name="Key name to rotate")
    async def rotate_mcp_key(self, interaction: discord.Interaction, name: str) -> None:
        if not await ensure_owner(interaction):
            return
        if not await ensure_valid_mcp_key_name(interaction, name):
            return

        try:
            rotated = await self._mcp_api_key_repository.rotate(name)
        except ApiKeyNotFound:
            await interaction.response.send_message(
                f"MCP API key `{name}` was not found.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Rotated MCP API key "
            f"`{rotated.name}`. Copy the replacement now; it will not be shown again.\n"
            f"Plaintext key: `{rotated.plaintext_key}`",
            ephemeral=True,
        )

    @mcp_group.command(name="delete", description="Delete an MCP API key")
    @app_commands.describe(name="Key name to delete")
    async def delete_mcp_key(self, interaction: discord.Interaction, name: str) -> None:
        if not await ensure_owner(interaction):
            return
        if not await ensure_valid_mcp_key_name(interaction, name):
            return

        try:
            await self._mcp_api_key_repository.delete(name)
        except ApiKeyNotFound:
            await interaction.response.send_message(
                f"MCP API key `{name}` was not found.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Deleted MCP API key `{name}`.",
            ephemeral=True,
        )

    @llm_group.command(name="add", description="Grant LLM model selection access")
    @app_commands.describe(user_id="Discord user ID to grant access")
    async def add_llm_access(
        self,
        interaction: discord.Interaction,
        user_id: str,
    ) -> None:
        if not await ensure_owner(interaction):
            return
        parsed_user_id = await parse_user_id(interaction, user_id)
        if parsed_user_id is None:
            return
        try:
            await self._model_access_repository.add(parsed_user_id)
        except LlmModelAccessAlreadyGranted:
            await interaction.response.send_message(
                f"<@{parsed_user_id}> (`{parsed_user_id}`) already has LLM model selection access.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await interaction.response.send_message(
            f"Granted LLM model selection access to <@{parsed_user_id}> (`{parsed_user_id}`).",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @llm_group.command(name="remove", description="Remove LLM model selection access")
    @app_commands.describe(user_id="Discord user ID to remove")
    async def remove_llm_access(
        self,
        interaction: discord.Interaction,
        user_id: str,
    ) -> None:
        if not await ensure_owner(interaction):
            return
        parsed_user_id = await parse_user_id(interaction, user_id)
        if parsed_user_id is None:
            return
        try:
            await self._model_access_repository.remove(parsed_user_id)
        except LlmModelAccessNotFound:
            await interaction.response.send_message(
                f"<@{parsed_user_id}> (`{parsed_user_id}`) does not have LLM model selection access.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await interaction.response.send_message(
            f"Removed LLM model selection access from <@{parsed_user_id}> (`{parsed_user_id}`).",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @llm_group.command(name="list", description="List LLM model selection access")
    async def list_llm_access(self, interaction: discord.Interaction) -> None:
        if not await ensure_owner(interaction):
            return
        entries = await self._model_access_repository.list()
        view = build_llm_access_list_view(entries)
        await interaction.response.send_message(
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @setting_group.command(name="nanobot", description="Configure Nanobot settings")
    async def nanobot(self, interaction: discord.Interaction) -> None:
        if not await ensure_owner(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message(
                _GUILD_REQUIRED_MESSAGE,
                ephemeral=True,
            )
            return

        policy = await self._nanobot_policy_repository.get(
            GuildId(str(interaction.guild.id))
        )
        view = NanobotSettingsView(
            policy_repository=self._nanobot_policy_repository,
            guild=interaction.guild,
            owner_check=interaction.client,
            policy=policy,
        )
        await interaction.response.send_message(
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


__all__ = ("Setting",)
