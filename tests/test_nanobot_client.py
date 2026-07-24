from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

import anyio
import pytest
from nanobot import StreamEvent

from rosetta.utils.config import NanobotSetting
from rosetta.utils.nanobot_client import (
    NanobotClientBusy,
    NanobotClientClosed,
    NanobotRunAccepted,
    NanobotRunRequest,
    NanobotSdkClient,
)
from rosetta.utils.nanobot_response import (
    NanobotFinalText,
    NanobotPublicFailure,
    NanobotTextDelta,
    NanobotToolActivity,
)

pytestmark = pytest.mark.anyio

type NormalizedEvent = (
    NanobotTextDelta | NanobotFinalText | NanobotPublicFailure | NanobotToolActivity
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(slots=True)
class ControlledStream:
    events: list[StreamEvent]
    entered: anyio.Event = field(default_factory=anyio.Event)
    release: anyio.Event = field(default_factory=anyio.Event)
    closed: bool = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> StreamEvent:
        self.entered.set()
        if self.events:
            return self.events.pop(0)
        try:
            await self.release.wait()
        except anyio.get_cancelled_exc_class():
            self.closed = True
            raise
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)
class FakeNanobot:
    streams: list[ControlledStream]
    calls: list[tuple[str, str, str, str, str]] = field(default_factory=list)
    close_count: int = 0

    def stream(
        self,
        message: str,
        *,
        session_key: str,
        channel: str,
        chat_id: str,
        sender_id: str,
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append((message, session_key, channel, chat_id, sender_id))
        return self.streams.pop(0)

    async def aclose(self) -> None:
        self.close_count += 1


def request(session_key: str, prompt: str = "hello") -> NanobotRunRequest:
    return NanobotRunRequest(prompt=prompt, session_key=session_key)


async def collect(accepted: NanobotRunAccepted) -> list[NormalizedEvent]:
    return [event async for event in accepted.events]


async def test_create_constructs_public_nanobot_from_config_path(
    tmp_path: Path,
) -> None:
    # Given: Nanobot settings point at an operator-owned config path.
    config_path = tmp_path / "nanobot.json"
    settings = NanobotSetting(CONFIG_PATH=config_path, MAX_CONCURRENT_RUNS=2)
    bot = FakeNanobot(streams=[])
    paths: list[Path] = []

    def factory(path: Path) -> FakeNanobot:
        paths.append(path)
        return bot

    # When: the production adapter is created through the injectable factory seam.
    client = NanobotSdkClient.create(settings, factory=factory)

    # Then: construction used the public config-path facade and kept the bound.
    assert paths == [config_path]
    assert client.max_concurrent_runs == 2


async def test_stream_maps_arguments_and_normalizes_documented_events() -> None:
    # Given: the SDK emits public 0.2.2 stream event variants.
    stream = ControlledStream(
        events=[
            StreamEvent(type="run.started"),
            StreamEvent(type="text.delta", delta="hel"),
            StreamEvent(type="reasoning.delta", delta="hidden"),
            StreamEvent(type="reasoning.completed"),
            StreamEvent(
                type="tool.started", name="search", arguments={"secret": "nope"}
            ),
            StreamEvent(type="tool.completed", name="search"),
            StreamEvent(type="tool.failed", name="play", error="private detail"),
            StreamEvent(type="text.completed", content="hello"),
            StreamEvent(type="run.completed", content="hello final"),
        ]
    )
    bot = FakeNanobot(streams=[stream, ControlledStream(events=[])])
    client = NanobotSdkClient(bot=bot, max_concurrent_runs=1)

    # When: a Discord session request is run through the adapter.
    result = await client.run(request("discord:10:20:30"))

    # Then: SDK arguments are deterministic and renderer events are public-safe.
    assert isinstance(result, NanobotRunAccepted)
    assert bot.calls == [
        ("hello", "discord:10:20:30", "discord", "discord:10:20", "30")
    ]
    assert await collect(result) == [
        NanobotTextDelta("hel"),
        NanobotToolActivity("search"),
        NanobotToolActivity("play"),
        NanobotFinalText("hello"),
        NanobotFinalText("hello final"),
    ]


async def test_duplicate_session_returns_busy_without_starting_second_stream() -> None:
    # Given: one session is already in flight.
    first_stream = ControlledStream(events=[])
    second_stream = ControlledStream(events=[])
    bot = FakeNanobot(streams=[first_stream, second_stream])
    client = NanobotSdkClient(bot=bot, max_concurrent_runs=2)
    first = await client.run(request("discord:10:20:30"))
    assert isinstance(first, NanobotRunAccepted)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(consume_until_entered, first.events, first_stream.entered)
        await first_stream.entered.wait()

        # When: the same session asks for another turn while active.
        duplicate = await client.run(request("discord:10:20:30", prompt="again"))

        # Then: the duplicate is rejected immediately and no second SDK stream starts.
        assert duplicate == NanobotClientBusy(session_key="discord:10:20:30")
        assert len(bot.calls) == 1
        first_stream.release.set()
        task_group.cancel_scope.cancel()


async def test_global_capacity_allows_two_distinct_sessions_under_limit() -> None:
    # Given: two different sessions and a global bound of two.
    streams = [
        ControlledStream(events=[StreamEvent(type="text.delta", delta=text)])
        for text in ("a", "b")
    ]
    bot = FakeNanobot(streams=streams.copy())
    client = NanobotSdkClient(bot=bot, max_concurrent_runs=2)
    first = await client.run(request("discord:10:20:30"))
    second = await client.run(request("discord:10:21:30"))
    assert isinstance(first, NanobotRunAccepted)
    assert isinstance(second, NanobotRunAccepted)

    # When: both normalized streams are consumed concurrently.
    results: list[list[NormalizedEvent]] = []
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(collect_into, first, results)
        task_group.start_soon(collect_into, second, results)
        await streams[0].entered.wait()
        await streams[1].entered.wait()
        streams[0].release.set()
        streams[1].release.set()

    # Then: both sessions ran without serializing at the adapter boundary.
    assert sorted(result[0].text for result in results) == ["a", "b"]
    assert len(bot.calls) == 2


async def test_close_during_active_stream_cancels_stream_and_closes_sdk_once() -> None:
    # Given: an active stream is blocked inside the SDK iterator.
    stream = ControlledStream(events=[])
    bot = FakeNanobot(streams=[stream, ControlledStream(events=[])])
    client = NanobotSdkClient(bot=bot, max_concurrent_runs=1)
    accepted = await client.run(request("discord:10:20:30"))
    assert isinstance(accepted, NanobotRunAccepted)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(consume_until_entered, accepted.events, stream.entered)
        await stream.entered.wait()

        # When: the adapter is closed during the active stream.
        await client.aclose()
        await client.aclose()
        task_group.cancel_scope.cancel()

    # Then: active work was cancelled, SDK close is idempotent, and new work is rejected.
    assert stream.closed
    assert bot.close_count == 1
    assert await client.run(request("discord:10:20:31")) == NanobotClientClosed()


async def test_close_after_accepted_run_without_iteration_finishes_boundedly() -> None:
    # Given: a run was accepted but its normalized event stream was never iterated.
    stream = ControlledStream(events=[])
    bot = FakeNanobot(streams=[stream])
    client = NanobotSdkClient(bot=bot, max_concurrent_runs=1)
    accepted = await client.run(request("discord:10:20:30"))
    assert isinstance(accepted, NanobotRunAccepted)

    # When: the client is closed before the caller starts consuming events.
    with anyio.fail_after(0.1):
        await client.aclose()

    # Then: upstream stream/client cleanup happened exactly once and new work is closed.
    assert stream.closed
    assert bot.close_count == 1
    assert await client.run(request("discord:10:20:31")) == NanobotClientClosed()


async def test_event_stream_close_before_iteration_releases_lifecycle_state() -> None:
    # Given: a run was accepted and the caller closes its event stream immediately.
    first_stream = ControlledStream(events=[])
    retry_stream = ControlledStream(events=[])
    bot = FakeNanobot(streams=[first_stream, retry_stream])
    client = NanobotSdkClient(bot=bot, max_concurrent_runs=1)
    accepted = await client.run(request("discord:10:20:30"))
    assert isinstance(accepted, NanobotRunAccepted)

    # When: the normalized stream is closed before first iteration.
    await accepted.events.aclose()

    # Then: upstream stream closed and the same session can be accepted again.
    assert first_stream.closed
    retry = await client.run(request("discord:10:20:30"))
    assert isinstance(retry, NanobotRunAccepted)
    await retry.events.aclose()


async def test_cancellation_preserves_caller_cancellation() -> None:
    # Given: a consumer is cancelled while reading an active stream.
    stream = ControlledStream(events=[])
    bot = FakeNanobot(streams=[stream, ControlledStream(events=[])])
    client = NanobotSdkClient(bot=bot, max_concurrent_runs=1)
    accepted = await client.run(request("discord:10:20:30"))
    assert isinstance(accepted, NanobotRunAccepted)

    # When / Then: external timeout cancellation reaches the caller and cleanup still runs.
    with pytest.raises(TimeoutError):
        with anyio.fail_after(0.01):
            await anext(accepted.events)
    assert stream.closed
    retry = await client.run(request("discord:10:20:30"))
    assert isinstance(retry, NanobotRunAccepted)
    await retry.events.aclose()


async def test_run_failed_event_maps_to_public_failure_and_stops() -> None:
    # Given: Nanobot reports a documented run failure event.
    stream = ControlledStream(
        events=[StreamEvent(type="run.failed", error="provider key")]
    )
    bot = FakeNanobot(streams=[stream])
    client = NanobotSdkClient(bot=bot, max_concurrent_runs=1)
    accepted = await client.run(request("discord:10:20:30"))
    assert isinstance(accepted, NanobotRunAccepted)

    # When: the event is normalized.
    events = await collect(accepted)

    # Then: private provider details are hidden behind a stable public failure.
    assert events == [
        NanobotPublicFailure(message="Nanobot could not complete this request.")
    ]


async def consume_until_entered(
    events: AsyncIterator[NormalizedEvent],
    entered: anyio.Event,
) -> None:
    async for _event in events:
        if entered.is_set():
            return


async def collect_into(
    accepted: NanobotRunAccepted,
    results: list[list[NormalizedEvent]],
) -> None:
    results.append(await collect(accepted))


def test_production_adapter_avoids_private_nanobot_apis() -> None:
    # Given: the production adapter source is available for static scanning.
    source = Path("rosetta/utils/nanobot_client.py").read_text(encoding="utf-8")

    # When / Then: banned private Nanobot seams do not appear.
    assert "_loop" not in source
    assert "AgentLoop" not in source
    assert "nanobot.agent" not in source
