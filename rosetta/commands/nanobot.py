from __future__ import annotations

from typing import Protocol, assert_never

import discord
from discord import app_commands
from discord.ext import commands

from rosetta.utils.cog import Cog
from rosetta.utils.nanobot_client import (
    NanobotClient,
    NanobotClientBusy,
    NanobotClientClosed,
    NanobotRunAccepted,
    NanobotRunRequest,
)
from rosetta.utils.nanobot_message import (
    BotUserId,
    NanobotTurnRequest,
    parse_nanobot_message,
)
from rosetta.utils.nanobot_policy import (
    GuildId,
    GuildPolicyLoadError,
    GuildPolicyRepository,
)
from rosetta.utils.nanobot_response import (
    NanobotRenderingFailure,
    render_nanobot_response,
)
from rosetta.utils.views.Nanobot import NanobotPolicyStore, NanobotSettingsView

BUSY_MESSAGE = "Nanobot is already handling your previous request."
CLOSED_MESSAGE = "Nanobot is shutting down. Try again later."
CONFIG_MESSAGE = "Nanobot is not configured for this server."
POLICY_ERROR_MESSAGE = "Nanobot settings are unavailable. Try again later."


class BotUserLike(Protocol):
    id: int


class BotLike(Protocol):
    user: BotUserLike | None


class NanobotReplyTarget(Protocol):
    async def reply(
        self,
        *,
        content: str,
        mention_author: bool,
        allowed_mentions: discord.AllowedMentions,
    ) -> discord.Message: ...


class Nanobot(Cog):
    nanobot_group = app_commands.Group(
        name="nanobot",
        description="Nanobot administration commands",
        allowed_installs=app_commands.AppInstallationType(guild=True, user=False),
        allowed_contexts=app_commands.AppCommandContext(
            guild=True,
            dm_channel=False,
            private_channel=False,
        ),
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(
        self,
        bot: commands.Bot | BotLike | None,
        policy_repository: NanobotPolicyStore,
        client: NanobotClient | None = None,
    ) -> None:
        super().__init__(bot=bot)
        self._policy_repository = policy_repository
        self._client = client
        self._client_closed = False

    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message) -> None:
        bot_user = self.bot.user
        if bot_user is None:
            return

        turn = parse_nanobot_message(message, BotUserId(str(bot_user.id)))
        if turn is None:
            return
        if not await self._policy_allows(turn):
            return
        if self._client is None:
            await _safe_reply(message, CONFIG_MESSAGE)
            return

        async with message.channel.typing():
            start = await self._client.run(_run_request(turn))
        match start:
            case NanobotRunAccepted(events=events):
                try:
                    await render_nanobot_response(message, events)
                except NanobotRenderingFailure:
                    return
            case NanobotClientBusy():
                await _safe_reply(message, BUSY_MESSAGE)
            case NanobotClientClosed():
                await _safe_reply(message, CLOSED_MESSAGE)
            case unreachable:
                assert_never(unreachable)

    async def aclose(self) -> None:
        if self._client_closed:
            return
        self._client_closed = True
        if self._client is not None:
            await self._client.aclose()

    @nanobot_group.command(
        name="settings", description="Configure Nanobot mention policy"
    )
    @app_commands.default_permissions(administrator=True)
    async def settings(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Nanobot settings are only available in a server.",
                ephemeral=True,
            )
            return
        if not interaction.permissions.administrator:
            await interaction.response.send_message(
                "Only server administrators can view Nanobot settings.",
                ephemeral=True,
            )
            return

        policy = await self._policy_repository.get(GuildId(str(interaction.guild.id)))
        view = NanobotSettingsView(
            policy_repository=self._policy_repository,
            guild=interaction.guild,
            user=interaction.user,
            policy=policy,
        )
        await interaction.response.send_message(
            content=view.render_text(),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _policy_allows(self, turn: NanobotTurnRequest) -> bool:
        try:
            policy = await self._policy_repository.get(turn.policy_lookup.guild_id)
        except GuildPolicyLoadError:
            return False
        return (
            policy.enabled
            and turn.policy_lookup.policy_channel_id in policy.channel_ids
        )


def _run_request(turn: NanobotTurnRequest) -> NanobotRunRequest:
    prompt_sections = [turn.context_prefix]
    if turn.reply_context_section is not None:
        prompt_sections.append(turn.reply_context_section)
    prompt_sections.append(turn.user_message_section)
    return NanobotRunRequest(
        prompt="\n\n".join(prompt_sections),
        session_key=turn.session_key,
    )


async def _safe_reply(target: NanobotReplyTarget, content: str) -> None:
    try:
        await target.reply(
            content=content,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException:
        return


__all__ = ("Nanobot", "GuildPolicyRepository")
