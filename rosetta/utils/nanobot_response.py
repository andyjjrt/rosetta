from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final, Protocol, Self, assert_never

import anyio
import discord

EDIT_INTERVAL_SECONDS: Final = 1.0
FINAL_CHUNK_LIMIT: Final = 1900
LIVE_PREVIEW_LIMIT: Final = 1990
INITIAL_REPLY_CONTENT: Final = "…"

logger = logging.getLogger(__name__)


class NanobotRenderOutcome(Enum):
    SUCCEEDED = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class NanobotTextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class NanobotFinalText:
    text: str


@dataclass(frozen=True, slots=True)
class NanobotPublicFailure:
    message: str


@dataclass(frozen=True, slots=True)
class NanobotToolActivity:
    tool_name: str


type NanobotEvent = (
    NanobotTextDelta | NanobotFinalText | NanobotPublicFailure | NanobotToolActivity
)


@dataclass(frozen=True, slots=True)
class NanobotRenderingFailure(Exception):
    operation: str

    def __str__(self) -> str:
        return f"Discord rejected Nanobot response while trying to {self.operation}"


class NanobotEventStream(Protocol):
    def __aiter__(self) -> Self: ...

    async def __anext__(self) -> NanobotEvent: ...

    async def aclose(self) -> None: ...


class NanobotRenderClock(Protocol):
    def now(self) -> float: ...

    async def sleep_until(self, target_seconds: float) -> None: ...


class NanobotDiscordMessage(Protocol):
    channel: NanobotDiscordChannel

    async def edit(
        self, *, content: str, allowed_mentions: discord.AllowedMentions
    ) -> None: ...


class NanobotDiscordChannel(Protocol):
    async def send(
        self, *, content: str, allowed_mentions: discord.AllowedMentions
    ) -> NanobotDiscordMessage: ...


class NanobotDiscordResponder(Protocol):
    async def reply(
        self,
        *,
        content: str,
        mention_author: bool,
        allowed_mentions: discord.AllowedMentions,
    ) -> NanobotDiscordMessage: ...


@dataclass(frozen=True, slots=True)
class AnyioRenderClock:
    def now(self) -> float:
        return anyio.current_time()

    async def sleep_until(self, target_seconds: float) -> None:
        delay_seconds = target_seconds - self.now()
        if delay_seconds > 0:
            await anyio.sleep(delay_seconds)


async def render_nanobot_response(
    responder: NanobotDiscordResponder,
    stream: NanobotEventStream,
    clock: NanobotRenderClock | None = None,
) -> NanobotRenderOutcome:
    render_clock = clock or AnyioRenderClock()
    try:
        message = await _reply(responder, INITIAL_REPLY_CONTENT)
        state = _RenderState(last_preview_at=render_clock.now() - EDIT_INTERVAL_SECONDS)
        async for event in stream:
            match event:
                case NanobotTextDelta(text=text):
                    state.text += text
                    await _flush_preview(message, state, render_clock)
                case NanobotToolActivity(tool_name=tool_name):
                    state.tool_name = tool_name
                    await _flush_preview(message, state, render_clock)
                case NanobotPublicFailure(message=public_message):
                    await _wait_for_edit_slot(state, render_clock)
                    await _edit(message, _preview(public_message))
                    return NanobotRenderOutcome.FAILED
                case NanobotFinalText(text=final_text):
                    await _flush_final(
                        responder, message, final_text, state, render_clock
                    )
                    return NanobotRenderOutcome.SUCCEEDED
                case unreachable:
                    assert_never(unreachable)
        await _flush_final(responder, message, state.text, state, render_clock)
        return NanobotRenderOutcome.SUCCEEDED
    finally:
        await _close_stream(stream)


@dataclass(slots=True)
class _RenderState:
    text: str = ""
    tool_name: str = ""
    last_preview_at: float = 0.0
    preview_sent: bool = False


async def _flush_preview(
    message: NanobotDiscordMessage,
    state: _RenderState,
    clock: NanobotRenderClock,
) -> None:
    now = clock.now()
    if now - state.last_preview_at < EDIT_INTERVAL_SECONDS:
        return
    content = _live_content(state)
    if not content:
        return
    await _edit(message, content)
    state.last_preview_at = now
    state.preview_sent = True


def _live_content(state: _RenderState) -> str:
    if state.text:
        return _preview(state.text)
    if state.tool_name:
        return _preview(f"Using tool: {state.tool_name[:80]}")
    return ""


def _preview(text: str) -> str:
    if len(text) < LIVE_PREVIEW_LIMIT:
        return text
    return text[-(LIVE_PREVIEW_LIMIT - 1) :]


async def _flush_final(
    responder: NanobotDiscordResponder,
    message: NanobotDiscordMessage,
    final_text: str,
    state: _RenderState,
    clock: NanobotRenderClock,
) -> None:
    await _wait_for_edit_slot(state, clock)
    first_chunk, *remaining_chunks = _final_chunks(final_text)
    await _edit(message, first_chunk)
    for chunk in remaining_chunks:
        await _send(message.channel, chunk)


async def _wait_for_edit_slot(state: _RenderState, clock: NanobotRenderClock) -> None:
    if state.preview_sent:
        await clock.sleep_until(state.last_preview_at + EDIT_INTERVAL_SECONDS)


def _final_chunks(text: str) -> list[str]:
    if not text:
        return [""]
    return [
        text[index : index + FINAL_CHUNK_LIMIT]
        for index in range(0, len(text), FINAL_CHUNK_LIMIT)
    ]


async def _reply(
    responder: NanobotDiscordResponder, content: str
) -> NanobotDiscordMessage:
    try:
        return await responder.reply(
            content=content,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException as error:
        logger.warning("Discord rejected Nanobot initial reply", exc_info=error)
        raise NanobotRenderingFailure(operation="send the initial reply") from None


async def _edit(message: NanobotDiscordMessage, content: str) -> None:
    try:
        await message.edit(
            content=content,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException as error:
        logger.warning("Discord rejected Nanobot response edit", exc_info=error)
        raise NanobotRenderingFailure(operation="edit the response") from None


async def _send(channel: NanobotDiscordChannel, content: str) -> NanobotDiscordMessage:
    try:
        return await channel.send(
            content=content,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException as error:
        logger.warning("Discord rejected Nanobot response follow-up", exc_info=error)
        raise NanobotRenderingFailure(operation="send a response chunk") from None


async def _close_stream(stream: NanobotEventStream) -> None:
    try:
        await stream.aclose()
    except (OSError, RuntimeError) as error:
        logger.warning("Nanobot stream cleanup failed", exc_info=error)
        if sys.exception() is None:
            raise
