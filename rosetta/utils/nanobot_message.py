from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, NewType, Protocol

BotUserId = NewType("BotUserId", str)
ChannelId = NewType("ChannelId", str)
GuildId = NewType("GuildId", str)
UserId = NewType("UserId", str)
VoiceChannelId = NewType("VoiceChannelId", str)

NOT_CONNECTED: Final = "not-connected"


class DiscordGuildLike(Protocol):
    id: int


class DiscordChannelLike(Protocol):
    id: int


class DiscordVoiceStateLike(Protocol):
    channel: DiscordChannelLike | None


class DiscordAuthorLike(Protocol):
    id: int
    bot: bool
    voice: DiscordVoiceStateLike | None


class DiscordMessageLike(Protocol):
    content: str
    guild: DiscordGuildLike | None
    channel: DiscordChannelLike
    author: DiscordAuthorLike
    webhook_id: int | None


@dataclass(frozen=True, slots=True)
class NanobotPolicyLookup:
    guild_id: GuildId
    actual_channel_id: ChannelId
    policy_channel_id: ChannelId


@dataclass(frozen=True, slots=True)
class NanobotDiscordContext:
    guild_id: GuildId
    channel_id: ChannelId
    author_id: UserId
    voice_channel_id: VoiceChannelId | None


@dataclass(frozen=True, slots=True)
class NanobotTurnRequest:
    session_key: str
    policy_lookup: NanobotPolicyLookup
    context: NanobotDiscordContext
    context_prefix: str
    user_text: str
    reply_context_section: str | None
    user_message_section: str


@dataclass(frozen=True, slots=True)
class _DiscordReplyContext:
    author_id: UserId
    content: str


def parse_nanobot_message(
    message: DiscordMessageLike, bot_user_id: BotUserId
) -> NanobotTurnRequest | None:
    if message.guild is None or message.author.bot or message.webhook_id is not None:
        return None

    reply_context = _reply_context(message)
    user_text = _strip_current_bot_mentions(message.content, bot_user_id)
    if user_text is None:
        if reply_context is None or reply_context.author_id != UserId(bot_user_id):
            return None
        user_text = _normalize_user_text(message.content)
    if not user_text:
        return None

    guild_id = GuildId(str(message.guild.id))
    channel_id = ChannelId(str(message.channel.id))
    author_id = UserId(str(message.author.id))
    voice_channel_id = _current_author_voice_channel_id(message.author)
    policy_channel_id = _policy_channel_id(message.channel)
    context = NanobotDiscordContext(
        guild_id=guild_id,
        channel_id=channel_id,
        author_id=author_id,
        voice_channel_id=voice_channel_id,
    )
    return NanobotTurnRequest(
        session_key=f"discord:{guild_id}:{channel_id}:{author_id}",
        policy_lookup=NanobotPolicyLookup(
            guild_id=guild_id,
            actual_channel_id=channel_id,
            policy_channel_id=policy_channel_id,
        ),
        context=context,
        context_prefix=_context_prefix(context),
        user_text=user_text,
        reply_context_section=(
            _reply_context_section(reply_context)
            if reply_context is not None
            and reply_context.author_id != UserId(bot_user_id)
            else None
        ),
        user_message_section=_user_message_section(user_text),
    )


def _strip_current_bot_mentions(content: str, bot_user_id: BotUserId) -> str | None:
    exact_mention = rf"<@!?{re.escape(bot_user_id)}>"
    if re.search(exact_mention, content) is None:
        return None
    mention_with_padding = re.compile(rf"[ \t\r\n\f\v]*{exact_mention}[ \t\r\n\f\v]*")
    return _normalize_user_text(mention_with_padding.sub(" ", content))


def _normalize_user_text(content: str) -> str:
    return re.sub(r"[ \t\f\v\r]+", " ", content.strip())


def _reply_context(message: DiscordMessageLike) -> _DiscordReplyContext | None:
    reference = getattr(message, "reference", None)
    resolved = getattr(reference, "resolved", None)
    author = getattr(resolved, "author", None)
    author_id: int | None = getattr(author, "id", None)
    content: str | None = getattr(resolved, "content", None)
    if author_id is None or content is None:
        return None
    return _DiscordReplyContext(author_id=UserId(str(author_id)), content=content)


def _current_author_voice_channel_id(
    author: DiscordAuthorLike,
) -> VoiceChannelId | None:
    voice_state = author.voice
    if voice_state is None or voice_state.channel is None:
        return None
    return VoiceChannelId(str(voice_state.channel.id))


def _policy_channel_id(channel: DiscordChannelLike) -> ChannelId:
    parent = getattr(channel, "parent", None)
    if parent is None:
        return ChannelId(str(channel.id))
    return ChannelId(str(parent.id))


def _context_prefix(context: NanobotDiscordContext) -> str:
    voice_channel = context.voice_channel_id or NOT_CONNECTED
    return "\n".join(
        (
            "<rosetta-discord-context>",
            f"guild_id: {context.guild_id}",
            f"channel_id: {context.channel_id}",
            f"author_id: {context.author_id}",
            f"author_voice_channel_id: {voice_channel}",
            "</rosetta-discord-context>",
        )
    )


def _user_message_section(user_text: str) -> str:
    return "\n".join(("<discord-user-message>", user_text, "</discord-user-message>"))


def _reply_context_section(reply: _DiscordReplyContext) -> str:
    return "\n".join(
        (
            "<discord-referenced-message>",
            f"author_id: {reply.author_id}",
            "<content>",
            reply.content,
            "</content>",
            "</discord-referenced-message>",
        )
    )
