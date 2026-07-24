from __future__ import annotations

from dataclasses import dataclass, field

import anyio
import discord

from rosetta.utils.nanobot_client import (
    NanobotClientBusy,
    NanobotClientClosed,
    NanobotRunRequest,
    NanobotRunStart,
)
from rosetta.utils.nanobot_policy import ChannelId, GuildId, GuildPolicy
from rosetta.utils.nanobot_response import NanobotFinalText, NanobotTextDelta

type IgnoreCase = tuple[FakeBot, FakeMessage, CountingPolicyRepository]


@dataclass(slots=True)
class FakePermissions:
    administrator: bool


@dataclass(frozen=True, slots=True)
class FakeUser:
    id: int


@dataclass(frozen=True, slots=True)
class FakeGuild:
    id: int


@dataclass(frozen=True, slots=True)
class FakeVoiceState:
    channel: FakeChannel


@dataclass(frozen=True, slots=True)
class FakeAuthor:
    id: int
    bot: bool = False
    voice: FakeVoiceState | None = None


@dataclass(frozen=True, slots=True)
class FakeChannel:
    id: int
    parent: FakeChannel | None = None
    typing_entries: list[int] = field(default_factory=list)

    def typing(self) -> FakeTyping:
        return FakeTyping(self.typing_entries)


@dataclass(slots=True)
class FakeTyping:
    entries: list[int]

    async def __aenter__(self) -> None:
        self.entries.append(1)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None


@dataclass(slots=True)
class FakeReplyMessage:
    edits: list[str] = field(default_factory=list)

    async def edit(
        self, *, content: str, allowed_mentions: discord.AllowedMentions
    ) -> None:
        assert mention_policy_is_none(allowed_mentions)
        self.edits.append(content)


@dataclass(slots=True)
class FakeMessage:
    content: str
    guild: FakeGuild | None
    channel: FakeChannel
    author: FakeAuthor
    webhook_id: int | None = None
    replies: list[str] = field(default_factory=list)
    sends: list[str] = field(default_factory=list)
    mention_author_values: list[bool] = field(default_factory=list)
    reply_messages: list[FakeReplyMessage] = field(default_factory=list)

    async def reply(
        self,
        *,
        content: str,
        mention_author: bool,
        allowed_mentions: discord.AllowedMentions,
    ) -> FakeReplyMessage:
        assert mention_policy_is_none(allowed_mentions)
        self.replies.append(content)
        self.mention_author_values.append(mention_author)
        message = FakeReplyMessage()
        self.reply_messages.append(message)
        return message


@dataclass(slots=True)
class EventStream:
    events: list[NanobotTextDelta | NanobotFinalText]
    closed: bool = False

    def __aiter__(self) -> EventStream:
        return self

    async def __anext__(self) -> NanobotTextDelta | NanobotFinalText:
        if not self.events:
            raise StopAsyncIteration
        return self.events.pop(0)

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)
class BlockingEventStream:
    entered: anyio.Event = field(default_factory=anyio.Event)
    release: anyio.Event = field(default_factory=anyio.Event)
    closed: bool = False

    def __aiter__(self) -> BlockingEventStream:
        return self

    async def __anext__(self) -> NanobotTextDelta | NanobotFinalText:
        self.entered.set()
        await self.release.wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)
class FakeClient:
    starts: list[NanobotRunStart]
    calls: list[NanobotRunRequest] = field(default_factory=list)
    close_count: int = 0

    async def run(self, request: NanobotRunRequest) -> NanobotRunStart:
        self.calls.append(request)
        return self.starts.pop(0)

    async def aclose(self) -> None:
        self.close_count += 1


@dataclass(frozen=True, slots=True)
class SentInteractionMessage:
    content: str | None
    ephemeral: bool
    view: discord.ui.View | None
    allowed_mentions: discord.AllowedMentions | None


@dataclass(slots=True)
class FakeInteractionResponse:
    sent: list[SentInteractionMessage] = field(default_factory=list)

    async def send_message(
        self,
        content: str | None = None,
        *,
        ephemeral: bool = False,
        view: discord.ui.View | None = None,
        allowed_mentions: discord.AllowedMentions | None = None,
    ) -> None:
        self.sent.append(
            SentInteractionMessage(
                content=content,
                ephemeral=ephemeral,
                view=view,
                allowed_mentions=allowed_mentions,
            )
        )


@dataclass(slots=True)
class FakeInteraction:
    guild: FakeGuild | None
    user: FakeUser
    permissions: FakePermissions
    response: FakeInteractionResponse = field(default_factory=FakeInteractionResponse)


@dataclass(slots=True)
class CountingPolicyRepository:
    policy: GuildPolicy = GuildPolicy(enabled=True, channel_ids=frozenset())
    calls: int = 0

    async def get(self, guild_id: GuildId) -> GuildPolicy:
        self.calls += 1
        return self.policy

    async def set_enabled(self, guild_id: GuildId, *, enabled: bool) -> None:
        self.calls += 1


@dataclass(frozen=True, slots=True)
class FakeBotUser:
    id: int


@dataclass(slots=True)
class FakeBot:
    user: FakeBotUser | None = FakeBotUser(id=123)
    process_commands_calls: int = 0

    async def process_commands(self, message: FakeMessage) -> None:
        self.process_commands_calls += 1


def mention_policy_is_none(allowed_mentions: discord.AllowedMentions | None) -> bool:
    assert allowed_mentions is not None
    return allowed_mentions.to_dict() == {"parse": []}


def enabled_repository(channel_id: str = "20") -> CountingPolicyRepository:
    return CountingPolicyRepository(
        policy=GuildPolicy(enabled=True, channel_ids=frozenset({ChannelId(channel_id)}))
    )


def disabled_repository() -> CountingPolicyRepository:
    return CountingPolicyRepository(
        policy=GuildPolicy(enabled=False, channel_ids=frozenset())
    )


def mention_message(
    content: str = "<@123> hello",
    *,
    guild: FakeGuild | None = FakeGuild(id=10),
    channel: FakeChannel | None = None,
    author: FakeAuthor | None = None,
    webhook_id: int | None = None,
) -> FakeMessage:
    return FakeMessage(
        content=content,
        guild=guild,
        channel=channel or FakeChannel(id=20),
        author=author or FakeAuthor(id=30),
        webhook_id=webhook_id,
    )


def reconstructed_text(message: FakeMessage) -> str:
    return "".join(edit for reply in message.reply_messages for edit in reply.edits)


def ignore_cases() -> tuple[IgnoreCase, ...]:
    return (
        (FakeBot(user=None), mention_message(), enabled_repository()),
        (
            FakeBot(),
            mention_message(author=FakeAuthor(id=30, bot=True)),
            enabled_repository(),
        ),
        (FakeBot(), mention_message(webhook_id=99), enabled_repository()),
        (FakeBot(), mention_message(guild=None), enabled_repository()),
        (FakeBot(), mention_message(content="<@123>"), enabled_repository()),
        (FakeBot(), mention_message(), disabled_repository()),
        (FakeBot(), mention_message(channel=FakeChannel(id=21)), enabled_repository()),
        (
            FakeBot(),
            mention_message(channel=FakeChannel(id=44, parent=FakeChannel(id=40))),
            enabled_repository(channel_id="44"),
        ),
    )


def manual_blocked_messages() -> tuple[FakeMessage, ...]:
    return (
        mention_message(
            guild=FakeGuild(id=10),
            channel=FakeChannel(id=20),
            author=FakeAuthor(id=30),
        ),
        mention_message(channel=FakeChannel(id=21)),
        mention_message(guild=None),
        mention_message(author=FakeAuthor(id=30, bot=True)),
        mention_message(webhook_id=99),
        mention_message(content="<@123>"),
    )


def start_failures() -> tuple[tuple[NanobotRunStart, str], ...]:
    return (
        (
            NanobotClientBusy(session_key="discord:10:20:30"),
            "Nanobot is already handling your previous request.",
        ),
        (NanobotClientClosed(), "Nanobot is shutting down. Try again later."),
    )


def settings_denials() -> tuple[tuple[FakeInteraction, str], ...]:
    return (
        (
            FakeInteraction(
                guild=FakeGuild(id=10),
                user=FakeUser(id=13),
                permissions=FakePermissions(administrator=False),
            ),
            "Only server administrators",
        ),
        (
            FakeInteraction(
                guild=None,
                user=FakeUser(id=99),
                permissions=FakePermissions(administrator=True),
            ),
            "only available in a server",
        ),
    )
