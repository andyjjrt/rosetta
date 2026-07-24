from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Self

import anyio
import discord
import pytest

from rosetta.utils.nanobot_response import (
    NanobotEvent,
    NanobotFinalText,
    NanobotPublicFailure,
    NanobotRenderingFailure,
    NanobotTextDelta,
    NanobotToolActivity,
    render_nanobot_response,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(slots=True)
class ReplyCall:
    content: str
    mention_author: bool
    allowed_mentions: discord.AllowedMentions


@dataclass(slots=True)
class SendCall:
    content: str
    allowed_mentions: discord.AllowedMentions


@dataclass(slots=True)
class EditCall:
    content: str
    allowed_mentions: discord.AllowedMentions
    at_seconds: float


@dataclass(slots=True)
class DeterministicClock:
    current_seconds: float = 0.0
    sleep_targets: list[float] = field(default_factory=list)

    def now(self) -> float:
        return self.current_seconds

    async def sleep_until(self, target_seconds: float) -> None:
        self.sleep_targets.append(target_seconds)
        if target_seconds > self.current_seconds:
            self.current_seconds = target_seconds


@dataclass(slots=True)
class HttpResponse:
    status: int = 500
    reason: str = "test failure"


class MessageChannelFake(Protocol):
    async def send(
        self, *, content: str, allowed_mentions: discord.AllowedMentions
    ) -> FakeMessage: ...


@dataclass(slots=True)
class FakeMessage:
    clock: DeterministicClock
    channel: MessageChannelFake
    fail_next_edit: bool = False
    edits: list[EditCall] = field(default_factory=list)

    async def edit(
        self, *, content: str, allowed_mentions: discord.AllowedMentions
    ) -> None:
        if self.fail_next_edit:
            self.fail_next_edit = False
            raise discord.HTTPException(HttpResponse(), "discord exploded")
        self.edits.append(
            EditCall(
                content=content,
                allowed_mentions=allowed_mentions,
                at_seconds=self.clock.now(),
            )
        )


@dataclass(slots=True)
class FakeChannel:
    clock: DeterministicClock
    sends: list[SendCall]

    async def send(
        self, *, content: str, allowed_mentions: discord.AllowedMentions
    ) -> FakeMessage:
        self.sends.append(SendCall(content=content, allowed_mentions=allowed_mentions))
        return FakeMessage(self.clock, self)


@dataclass(slots=True)
class FakeResponder:
    clock: DeterministicClock
    fail_first_edit: bool = False
    fail_reply: bool = False
    replies: list[ReplyCall] = field(default_factory=list)
    sends: list[SendCall] = field(default_factory=list)
    messages: list[FakeMessage] = field(default_factory=list)

    async def reply(
        self,
        *,
        content: str,
        mention_author: bool,
        allowed_mentions: discord.AllowedMentions,
    ) -> FakeMessage:
        if self.fail_reply:
            raise discord.HTTPException(HttpResponse(), "initial reply failed")
        self.replies.append(
            ReplyCall(
                content=content,
                mention_author=mention_author,
                allowed_mentions=allowed_mentions,
            )
        )
        message = FakeMessage(
            self.clock,
            FakeChannel(self.clock, self.sends),
            fail_next_edit=self.fail_first_edit,
        )
        self.messages.append(message)
        return message


@dataclass(slots=True)
class RealisticOriginalMessage:
    clock: DeterministicClock
    channel: FakeChannel
    replies: list[ReplyCall] = field(default_factory=list)
    reply_message: FakeMessage | None = None

    async def reply(
        self,
        *,
        content: str,
        mention_author: bool,
        allowed_mentions: discord.AllowedMentions,
    ) -> FakeMessage:
        self.replies.append(
            ReplyCall(
                content=content,
                mention_author=mention_author,
                allowed_mentions=allowed_mentions,
            )
        )
        self.reply_message = FakeMessage(self.clock, self.channel)
        return self.reply_message


@dataclass(slots=True)
class EventStream:
    events: list[NanobotEvent]
    close_calls: int = 0

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> NanobotEvent:
        if not self.events:
            raise StopAsyncIteration
        return self.events.pop(0)

    async def aclose(self) -> None:
        self.close_calls += 1


@dataclass(slots=True)
class BlockingStream:
    close_calls: int = 0
    delivered_first: bool = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> NanobotEvent:
        if not self.delivered_first:
            self.delivered_first = True
            return NanobotTextDelta("partial")
        await anyio.sleep_forever()

    async def aclose(self) -> None:
        self.close_calls += 1


def mention_policy_is_none(allowed_mentions: discord.AllowedMentions) -> bool:
    return allowed_mentions.to_dict() == {"parse": []}


async def test_coalesces_preview_and_suppresses_mentions_when_deltas_are_fast() -> None:
    # Given: fast deltas arrive before the deterministic clock reaches one second.
    clock = DeterministicClock()
    responder = FakeResponder(clock)
    stream = EventStream(
        [
            NanobotTextDelta("hello "),
            NanobotToolActivity(tool_name="search"),
            NanobotTextDelta("@everyone"),
            NanobotFinalText("hello @everyone"),
        ]
    )

    # When: the renderer consumes the normalized stream.
    await render_nanobot_response(responder, stream, clock=clock)

    # Then: Discord-visible calls are mention-safe and fast deltas are coalesced.
    assert [call.mention_author for call in responder.replies] == [False]
    assert all(
        mention_policy_is_none(call.allowed_mentions) for call in responder.replies
    )
    edits = responder.messages[0].edits
    assert all(mention_policy_is_none(call.allowed_mentions) for call in edits)
    assert [call.content for call in edits] == ["hello ", "hello @everyone"]
    assert [call.at_seconds for call in edits] == [0.0, 1.0]
    assert clock.sleep_targets == [1.0]
    assert stream.close_calls == 1


async def test_overflow_final_chunks_use_original_message_channel_send() -> None:
    # Given: a realistic Discord message exposes reply() and channel.send(), not send().
    final_text = "D" * 1900 + "E" * 1900 + "F" * 250
    clock = DeterministicClock(current_seconds=4.0)
    channel = FakeChannel(clock, [])
    original_message = RealisticOriginalMessage(clock, channel)
    stream = EventStream([NanobotFinalText(final_text)])

    # When: the renderer sends a multi-message final response.
    await render_nanobot_response(original_message, stream, clock=clock)

    # Then: overflow chunks use the channel surface with safe mention policy.
    assert original_message.reply_message is not None
    edited = [call.content for call in original_message.reply_message.edits]
    sent = [call.content for call in channel.sends]
    assert [len(content) for content in edited + sent] == [1900, 1900, 250]
    assert "".join(edited + sent) == final_text
    assert all(mention_policy_is_none(call.allowed_mentions) for call in channel.sends)


async def test_public_failure_is_safe_and_does_not_expose_provider_details() -> None:
    # Given: a normalized public failure carries only user-safe text.
    clock = DeterministicClock()
    responder = FakeResponder(clock)
    stream = EventStream(
        [NanobotPublicFailure("Nanobot is unavailable. Try again later.")]
    )

    # When: the renderer handles the failure.
    await render_nanobot_response(responder, stream, clock=clock)

    # Then: only the safe failure text is shown.
    assert [call.content for call in responder.messages[0].edits] == [
        "Nanobot is unavailable. Try again later."
    ]
    assert responder.sends == []


async def test_cancellation_closes_stream_and_emits_no_stale_final() -> None:
    # Given: an upstream stream that has produced a partial response and then blocks.
    clock = DeterministicClock()
    responder = FakeResponder(clock)
    stream = BlockingStream()

    # When: rendering is cancelled before a final event arrives.
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(render_nanobot_response, responder, stream, clock)
        with anyio.fail_after(1):
            while not stream.delivered_first:
                await anyio.sleep(0)
        task_group.cancel_scope.cancel()

    # Then: the upstream stream is closed and no final/send occurs after cancellation.
    assert stream.close_calls == 1
    assert [call.content for call in responder.messages[0].edits] == ["partial"]
    assert responder.sends == []


async def test_discord_http_failure_becomes_typed_rendering_failure() -> None:
    # Given: Discord rejects the first edit.
    clock = DeterministicClock()
    responder = FakeResponder(clock, fail_first_edit=True)
    stream = EventStream([NanobotTextDelta("hello")])

    # When / Then: the renderer raises a typed failure and does not duplicate sends.
    with pytest.raises(NanobotRenderingFailure, match="Discord rejected"):
        await render_nanobot_response(responder, stream, clock=clock)
    assert len(responder.replies) == 1
    assert responder.sends == []
    assert stream.close_calls == 1


async def test_initial_reply_failure_closes_stream_once_without_stale_sends() -> None:
    # Given: Discord rejects the initial reply before any stream event is consumed.
    stream = EventStream([])
    responder = FakeResponder(DeterministicClock(), fail_reply=True)

    # When / Then: the typed failure still closes upstream exactly once.
    with pytest.raises(NanobotRenderingFailure, match="initial reply"):
        await render_nanobot_response(responder, stream, clock=DeterministicClock())
    assert stream.close_calls == 1
    assert responder.sends == []
