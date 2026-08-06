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
from rosetta.utils.nanobot_response import (
    NanobotFinalText,
    NanobotPublicFailure,
    NanobotTextDelta,
)

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
class OperationRecord:
    name: str
    typing_depth: int
    detail: str | None = None
    emoji: str | None = None
    bot_user_id: int | None = None

    @property
    def typing_active(self) -> bool:
        return self.typing_depth > 0


@dataclass(slots=True)
class OperationTrace:
    records: list[OperationRecord] = field(default_factory=list)
    typing_depth: int = 0

    @property
    def typing_active(self) -> bool:
        return self.typing_depth > 0

    def record(
        self,
        name: str,
        *,
        detail: str | None = None,
        emoji: str | None = None,
        bot_user_id: int | None = None,
    ) -> None:
        self.records.append(
            OperationRecord(
                name=name,
                detail=detail,
                emoji=emoji,
                bot_user_id=bot_user_id,
                typing_depth=self.typing_depth,
            )
        )

    def enter_typing(self) -> None:
        self.typing_depth += 1
        self.record("typing.enter")

    def exit_typing(self) -> None:
        self.typing_depth -= 1
        self.record("typing.exit")


@dataclass(slots=True)
class BlockingCall:
    entered: anyio.Event = field(default_factory=anyio.Event)
    release: anyio.Event = field(default_factory=anyio.Event)

    async def wait(self) -> None:
        self.entered.set()
        await self.release.wait()


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
    operation_trace: OperationTrace = field(default_factory=OperationTrace)
    typing_enter_block: BlockingCall | None = None

    @property
    def typing_active_depth(self) -> int:
        return self.operation_trace.typing_depth

    def typing(self) -> FakeTyping:
        return FakeTyping(
            entries=self.typing_entries,
            operation_trace=self.operation_trace,
            enter_block=self.typing_enter_block,
        )


@dataclass(slots=True)
class FakeTyping:
    entries: list[int]
    operation_trace: OperationTrace
    enter_block: BlockingCall | None = None

    async def __aenter__(self) -> None:
        if self.enter_block is not None:
            self.operation_trace.record("typing.enter.block")
            await self.enter_block.wait()
        self.entries.append(1)
        self.operation_trace.enter_typing()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        self.operation_trace.exit_typing()


@dataclass(slots=True)
class FakeReplyMessage:
    operation_trace: OperationTrace = field(default_factory=OperationTrace)
    edits: list[str] = field(default_factory=list)

    async def edit(
        self, *, content: str, allowed_mentions: discord.AllowedMentions
    ) -> None:
        assert mention_policy_is_none(allowed_mentions)
        self.operation_trace.record("reply.edit", detail=content)
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
    reply_failures: list[BaseException] = field(default_factory=list)
    add_reaction_failures: list[BaseException] = field(default_factory=list)
    add_reaction_failures_by_emoji: dict[str, list[BaseException]] = field(
        default_factory=dict
    )
    add_reaction_blocks_by_emoji: dict[str, list[BlockingCall]] = field(
        default_factory=dict
    )
    remove_reaction_failures: list[BaseException] = field(default_factory=list)
    remove_reaction_blocks: list[BlockingCall] = field(default_factory=list)

    @property
    def operation_trace(self) -> OperationTrace:
        return self.channel.operation_trace

    async def reply(
        self,
        *,
        content: str,
        mention_author: bool,
        allowed_mentions: discord.AllowedMentions,
    ) -> FakeReplyMessage:
        assert mention_policy_is_none(allowed_mentions)
        self.operation_trace.record("source.reply", detail=content)
        if self.reply_failures:
            raise self.reply_failures.pop(0)
        self.replies.append(content)
        self.mention_author_values.append(mention_author)
        message = FakeReplyMessage(operation_trace=self.operation_trace)
        self.reply_messages.append(message)
        return message

    async def add_reaction(self, emoji: str) -> None:
        self.operation_trace.record("source.add_reaction", emoji=emoji)
        if blocks := self.add_reaction_blocks_by_emoji.get(emoji):
            await blocks.pop(0).wait()
        if failures := self.add_reaction_failures_by_emoji.get(emoji):
            raise failures.pop(0)
        if self.add_reaction_failures:
            raise self.add_reaction_failures.pop(0)

    async def remove_reaction(self, emoji: str, member: FakeBotUser) -> None:
        self.operation_trace.record(
            "source.remove_reaction",
            emoji=emoji,
            bot_user_id=member.id,
        )
        if self.remove_reaction_blocks:
            await self.remove_reaction_blocks.pop(0).wait()
        if self.remove_reaction_failures:
            raise self.remove_reaction_failures.pop(0)


@dataclass(slots=True)
class EventStream:
    events: list[NanobotTextDelta | NanobotFinalText | NanobotPublicFailure]
    unexpected_error: BaseException | None = None
    closed: bool = False
    close_count: int = 0

    def __aiter__(self) -> EventStream:
        return self

    async def __anext__(
        self,
    ) -> NanobotTextDelta | NanobotFinalText | NanobotPublicFailure:
        if not self.events:
            if self.unexpected_error is not None:
                raise self.unexpected_error
            raise StopAsyncIteration
        return self.events.pop(0)

    async def aclose(self) -> None:
        self.closed = True
        self.close_count += 1


@dataclass(slots=True)
class BlockingEventStream:
    entered: anyio.Event = field(default_factory=anyio.Event)
    release: anyio.Event = field(default_factory=anyio.Event)
    closed: bool = False
    close_count: int = 0

    def __aiter__(self) -> BlockingEventStream:
        return self

    async def __anext__(
        self,
    ) -> NanobotTextDelta | NanobotFinalText | NanobotPublicFailure:
        self.entered.set()
        await self.release.wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True
        self.close_count += 1


@dataclass(slots=True)
class FakeClient:
    starts: list[NanobotRunStart]
    operation_trace: OperationTrace = field(default_factory=OperationTrace)
    calls: list[NanobotRunRequest] = field(default_factory=list)
    run_failures: list[BaseException] = field(default_factory=list)
    close_count: int = 0

    async def run(self, request: NanobotRunRequest) -> NanobotRunStart:
        self.operation_trace.record("client.run", detail=request.session_key)
        self.calls.append(request)
        if self.run_failures:
            raise self.run_failures.pop(0)
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
