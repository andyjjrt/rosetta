from __future__ import annotations

import logging
from typing import Final, Protocol, assert_never

import anyio
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
    GuildPolicyLoadError,
    GuildPolicyRepository,
)
from rosetta.utils.nanobot_response import (
    NanobotRenderingFailure,
    NanobotRenderOutcome,
    render_nanobot_response,
)
from rosetta.utils.views.Nanobot import NanobotPolicyStore

BUSY_MESSAGE = "Nanobot is already handling your previous request."
CLOSED_MESSAGE = "Nanobot is shutting down. Try again later."
CONFIG_MESSAGE = "Nanobot is not configured for this server."
POLICY_ERROR_MESSAGE = "Nanobot settings are unavailable. Try again later."
PROCESSING_REACTION: Final = "⏳"
SUCCEEDED_REACTION: Final = "✅"
FAILED_REACTION: Final = "❌"

logger = logging.getLogger(__name__)


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


class NanobotReactionTarget(Protocol):
    async def add_reaction(self, emoji: str) -> None: ...

    async def remove_reaction(self, emoji: str, member: BotUserLike) -> None: ...


class RemovedNanobotGroup:
    allowed_installs = app_commands.AppInstallationType(guild=True, user=False)
    allowed_contexts = app_commands.AppCommandContext(
        guild=True,
        dm_channel=False,
        private_channel=False,
    )
    default_permissions = discord.Permissions(administrator=True)

    def get_command(self, name: str) -> None:
        return None


class Nanobot(Cog):
    nanobot_group: Final = RemovedNanobotGroup()

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

        body_entered = False
        try:
            async with message.channel.typing():
                body_entered = True
                terminal_add_started = False

                async def terminalize(terminal_reaction: str) -> None:
                    nonlocal terminal_add_started
                    await _safe_remove_reaction(message, PROCESSING_REACTION, bot_user)
                    terminal_add_started = True
                    await _safe_add_reaction(message, terminal_reaction)

                try:
                    await _safe_add_reaction(message, PROCESSING_REACTION)
                    if self._client is None:
                        await _safe_reply(message, CONFIG_MESSAGE)
                        await terminalize(FAILED_REACTION)
                        return

                    start = await self._client.run(_run_request(turn))
                    match start:
                        case NanobotRunAccepted(events=events):
                            outcome = await render_nanobot_response(message, events)
                            match outcome:
                                case NanobotRenderOutcome.SUCCEEDED:
                                    await terminalize(SUCCEEDED_REACTION)
                                case NanobotRenderOutcome.FAILED:
                                    await terminalize(FAILED_REACTION)
                                case unreachable:
                                    assert_never(unreachable)
                        case NanobotClientBusy():
                            await _safe_reply(message, BUSY_MESSAGE)
                            await terminalize(FAILED_REACTION)
                        case NanobotClientClosed():
                            await _safe_reply(message, CLOSED_MESSAGE)
                            await terminalize(FAILED_REACTION)
                        case unreachable:
                            assert_never(unreachable)
                except NanobotRenderingFailure as error:
                    if not terminal_add_started:
                        await _cleanup_terminalization(error, message, bot_user)
                    return
                except anyio.get_cancelled_exc_class() as error:
                    if not terminal_add_started:
                        await _cleanup_terminalization(error, message, bot_user)
                    raise
                except Exception as error:  # noqa: BLE001  # BROAD_EXCEPT_OK: listener cleanup preserves and re-raises unexpected lifecycle failures.
                    if not terminal_add_started:
                        await _cleanup_terminalization(error, message, bot_user)
                    raise
        except anyio.get_cancelled_exc_class() as error:
            if not body_entered:
                await _cleanup_terminalization(error, message, bot_user)
            raise
        except Exception as error:  # noqa: BLE001  # BROAD_EXCEPT_OK: typing entry cleanup preserves and re-raises primary failure.
            if not body_entered:
                await _cleanup_terminalization(error, message, bot_user)
            raise

    async def aclose(self) -> None:
        if self._client_closed:
            return
        self._client_closed = True
        if self._client is not None:
            await self._client.aclose()

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


async def _terminalize_reaction(
    target: NanobotReactionTarget,
    bot_user: BotUserLike,
    terminal_reaction: str,
) -> None:
    await _safe_remove_reaction(target, PROCESSING_REACTION, bot_user)
    await _safe_add_reaction(target, terminal_reaction)


async def _cleanup_terminalization(
    original: BaseException,
    target: NanobotReactionTarget,
    bot_user: BotUserLike,
) -> None:
    try:
        with anyio.CancelScope(shield=True):
            await _terminalize_reaction(target, bot_user, FAILED_REACTION)
    except BaseException as error:  # noqa: BLE001  # BROAD_EXCEPT_OK: cleanup preserves the primary listener failure.
        original.add_note(f"suppressed Nanobot terminalization cleanup error: {error}")


async def _safe_add_reaction(target: NanobotReactionTarget, emoji: str) -> None:
    try:
        await target.add_reaction(emoji)
    except discord.HTTPException as error:
        logger.warning("Discord rejected Nanobot reaction add", exc_info=error)


async def _safe_remove_reaction(
    target: NanobotReactionTarget,
    emoji: str,
    bot_user: BotUserLike,
) -> None:
    try:
        await target.remove_reaction(emoji, bot_user)
    except discord.HTTPException as error:
        logger.warning("Discord rejected Nanobot reaction removal", exc_info=error)


__all__ = ("Nanobot", "GuildPolicyRepository")
