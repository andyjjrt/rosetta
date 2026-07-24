from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self, assert_never

import anyio
from nanobot import Nanobot, StreamEvent

from rosetta.utils.config import NanobotSetting
from rosetta.utils.nanobot_response import (
    NanobotEvent,
    NanobotEventStream,
    NanobotFinalText,
    NanobotPublicFailure,
    NanobotTextDelta,
    NanobotToolActivity,
)

PUBLIC_FAILURE_MESSAGE = "Nanobot could not complete this request."
DISCORD_CHANNEL = "discord"


@dataclass(frozen=True, slots=True)
class NanobotRunRequest:
    prompt: str
    session_key: str


@dataclass(frozen=True, slots=True)
class NanobotRunAccepted:
    events: NanobotEventStream


@dataclass(frozen=True, slots=True)
class NanobotClientBusy:
    session_key: str


@dataclass(frozen=True, slots=True)
class NanobotClientClosed:
    pass


type NanobotRunStart = NanobotRunAccepted | NanobotClientBusy | NanobotClientClosed


class NanobotClient(Protocol):
    async def run(self, request: NanobotRunRequest) -> NanobotRunStart: ...

    async def aclose(self) -> None: ...


class NanobotFactory(Protocol):
    def __call__(self, config_path: Path) -> NanobotBot: ...


class NanobotBot(Protocol):
    def stream(
        self,
        message: str,
        *,
        session_key: str,
        channel: str,
        chat_id: str,
        sender_id: str,
    ) -> NanobotSdkEventStream: ...

    async def aclose(self) -> None: ...


class NanobotSdkEventStream(Protocol):
    def __aiter__(self) -> Self: ...

    async def __anext__(self) -> StreamEvent: ...

    async def aclose(self) -> None: ...


@dataclass(slots=True)
class _RunHandle:
    session_key: str
    cancel_scope: anyio.CancelScope
    done: anyio.Event
    stream: NanobotSdkEventStream
    closed: bool = False


class NanobotSdkClient:
    def __init__(self, bot: NanobotBot, max_concurrent_runs: int) -> None:
        self._bot = bot
        self._limiter = anyio.CapacityLimiter(max_concurrent_runs)
        self._lock = anyio.Lock()
        self._active_sessions: set[str] = set()
        self._handles: list[_RunHandle] = []
        self._closed = False
        self._sdk_closed = False
        self.max_concurrent_runs = max_concurrent_runs

    @classmethod
    def create(
        cls,
        settings: NanobotSetting,
        factory: NanobotFactory | None = None,
    ) -> NanobotSdkClient:
        bot_factory = factory or _nanobot_from_config
        return cls(
            bot=bot_factory(settings.CONFIG_PATH),
            max_concurrent_runs=settings.MAX_CONCURRENT_RUNS,
        )

    async def run(self, request: NanobotRunRequest) -> NanobotRunStart:
        async with self._lock:
            if self._closed:
                return NanobotClientClosed()
            if request.session_key in self._active_sessions:
                return NanobotClientBusy(session_key=request.session_key)
            self._active_sessions.add(request.session_key)
        stream_started = False
        try:
            stream = self._stream(request)
            stream_started = True
        finally:
            if not stream_started:
                async with self._lock:
                    self._active_sessions.discard(request.session_key)
        handle = _RunHandle(
            session_key=request.session_key,
            cancel_scope=anyio.CancelScope(),
            done=anyio.Event(),
            stream=stream,
        )
        async with self._lock:
            self._handles.append(handle)
        return NanobotRunAccepted(events=_NormalizedNanobotStream(self, handle=handle))

    async def aclose(self) -> None:
        async with self._lock:
            self._closed = True
            handles = tuple(self._handles)
        for handle in handles:
            handle.cancel_scope.cancel()
        for handle in handles:
            await self._finish(handle)
        for handle in handles:
            await handle.done.wait()
        async with self._lock:
            if self._sdk_closed:
                return
            self._sdk_closed = True
        await self._bot.aclose()

    async def _finish(self, handle: _RunHandle) -> None:
        already_closed = False
        async with self._lock:
            if handle.closed:
                already_closed = True
            else:
                handle.closed = True
                self._active_sessions.discard(handle.session_key)
                self._handles = [
                    active for active in self._handles if active is not handle
                ]
                handle.done.set()
        if not already_closed:
            await handle.stream.aclose()

    def _stream(self, request: NanobotRunRequest) -> NanobotSdkEventStream:
        chat_id, sender_id = _discord_ids(request.session_key)
        return self._bot.stream(
            request.prompt,
            session_key=request.session_key,
            channel=DISCORD_CHANNEL,
            chat_id=chat_id,
            sender_id=sender_id,
        )


def _nanobot_from_config(config_path: Path) -> NanobotBot:
    return Nanobot.from_config(config_path=config_path)


@dataclass(slots=True)
class _NormalizedNanobotStream:
    client: NanobotSdkClient
    handle: _RunHandle
    _events: NanobotEventStream | None = None

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> NanobotEvent:
        if self._events is None:
            self._events = self._create_events()
        return await self._events.__anext__()

    async def aclose(self) -> None:
        self.handle.cancel_scope.cancel()
        if self._events is not None:
            await self._events.aclose()
        else:
            with anyio.CancelScope(shield=True):
                await self.client._finish(self.handle)

    def _create_events(self) -> NanobotEventStream:
        return _events(self.client, self.handle)


async def _events(
    client: NanobotSdkClient,
    handle: _RunHandle,
) -> AsyncIterator[NanobotEvent]:
    try:
        async with client._limiter:
            with handle.cancel_scope:
                async for event in handle.stream:
                    normalized = _normalize_event(event)
                    if normalized is None:
                        continue
                    yield normalized
                    if isinstance(normalized, NanobotPublicFailure) or _is_terminal(
                        event
                    ):
                        return
    finally:
        with anyio.CancelScope(shield=True):
            await client._finish(handle)


def _discord_ids(session_key: str) -> tuple[str, str]:
    chat_id, sender_id = session_key.rsplit(":", maxsplit=1)
    return chat_id, sender_id


def _normalize_event(event: StreamEvent) -> NanobotEvent | None:
    match event.type:
        case "run.started":
            return None
        case "text.delta":
            return NanobotTextDelta(event.delta)
        case "text.completed":
            return NanobotFinalText(event.content)
        case "reasoning.delta":
            return None
        case "reasoning.completed":
            return None
        case "tool.started":
            return NanobotToolActivity(event.name or "tool")
        case "tool.completed":
            return None
        case "tool.failed":
            return NanobotToolActivity(event.name or "tool")
        case "run.completed":
            if event.result is not None and event.result.error is not None:
                return NanobotPublicFailure(message=PUBLIC_FAILURE_MESSAGE)
            if event.result is not None:
                return NanobotFinalText(event.result.content)
            return NanobotFinalText(event.content)
        case "run.failed":
            return NanobotPublicFailure(message=PUBLIC_FAILURE_MESSAGE)
        case unreachable:
            assert_never(unreachable)


def _is_terminal(event: StreamEvent) -> bool:
    return event.type in {"run.completed", "run.failed"}
