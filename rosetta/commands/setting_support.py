from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

import discord

from rosetta.utils.llm_model_access import LlmModelAccessEntry
from rosetta.utils.mcp_api_keys import KEY_PREFIX, McpApiKeyMetadata
from rosetta.utils.views.Settings import (
    SettingsListConfig,
    SettingsListRow,
    SettingsListView,
)

_DENIAL_MESSAGE: Final = "Only the bot owner can use /setting."
_NAME_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


async def ensure_owner(interaction: discord.Interaction) -> bool:
    if await interaction.client.is_owner(interaction.user):
        return True
    await interaction.response.send_message(_DENIAL_MESSAGE, ephemeral=True)
    return False


async def ensure_valid_mcp_key_name(
    interaction: discord.Interaction,
    name: str,
) -> bool:
    if KEY_PREFIX in name:
        await interaction.response.send_message(
            "MCP API key names cannot contain the reserved API key scheme.",
            ephemeral=True,
        )
        return False
    if _NAME_PATTERN.fullmatch(name) is not None:
        return True
    await interaction.response.send_message(
        "MCP API key names must be 1-64 characters using only letters, numbers, hyphens, or underscores.",
        ephemeral=True,
    )
    return False


async def parse_user_id(
    interaction: discord.Interaction,
    user_id: str,
) -> int | None:
    if user_id.isdecimal() and (parsed_user_id := int(user_id)) > 0:
        return parsed_user_id
    await interaction.response.send_message(
        "Discord user ID must be a positive integer.",
        ephemeral=True,
    )
    return None


def format_key_metadata(key: McpApiKeyMetadata) -> str:
    visible_prefix = key.key_prefix.removeprefix(KEY_PREFIX)
    rotated = key.rotated_at or "never"
    return (
        f"- `{key.name}`: prefix `{visible_prefix}`, "
        f"fingerprint `{key.fingerprint}`, created `{key.created_at}`, "
        f"rotated `{rotated}`"
    )


async def _is_bot_owner(interaction: discord.Interaction) -> bool:
    return await interaction.client.is_owner(interaction.user)


def build_mcp_key_list_view(
    keys: Sequence[McpApiKeyMetadata],
) -> SettingsListView[str]:
    rows = tuple(
        SettingsListRow(
            title=key.name.replace(KEY_PREFIX, "[reserved-prefix]"),
            detail=format_key_metadata(key).removeprefix(f"- `{key.name}`: "),
            value=key.name.replace(KEY_PREFIX, "[reserved-prefix]"),
        )
        for key in keys
    )
    return SettingsListView(
        SettingsListConfig(
            title="MCP API keys",
            rows=rows,
            empty_message="No MCP API keys have been created.",
            owner_check=_is_bot_owner,
            custom_id_prefix="settings:mcp",
        )
    )


def build_llm_access_list_view(
    entries: Sequence[LlmModelAccessEntry],
) -> SettingsListView[int]:
    rows = tuple(
        SettingsListRow(
            title=f"<@{entry.user_id}>",
            detail=f"ID: `{entry.user_id}`\nAdded: `{entry.created_at}`",
            value=entry.user_id,
        )
        for entry in entries
    )
    return SettingsListView(
        SettingsListConfig(
            title="Users with LLM model selection access",
            rows=rows,
            empty_message="No users have LLM model selection access.",
            owner_check=_is_bot_owner,
            custom_id_prefix="settings:llm",
        )
    )
