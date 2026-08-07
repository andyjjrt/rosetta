from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

import anyio
import discord
import pytest

import rosetta.commands.nanobot as nanobot_module
from rosetta.commands.nanobot import Nanobot
from rosetta.utils.nanobot_client import (
    NanobotClientBusy,
    NanobotClientClosed,
    NanobotRunAccepted,
    NanobotRunStart,
)
from rosetta.utils.nanobot_response import (
    NanobotFinalText,
    NanobotPublicFailure,
    NanobotRenderingFailure,
    NanobotTextDelta,
)
from tests.nanobot_cog_fakes import (
    BlockingCall,
    BlockingEventStream,
    CountingPolicyRepository,
    EventStream,
    FakeAuthor,
    FakeBot,
    FakeChannel,
    FakeClient,
    FakeMessage,
    FakeVoiceState,
    disabled_repository,
    enabled_repository,
    ignore_cases,
    manual_blocked_messages,
    mention_message,
    reconstructed_text,
    start_failures,
)

pytestmark = pytest.mark.anyio


@dataclass(slots=True)
class HttpResponse:
    status: int = 500
    reason: str = "test failure"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def http_failure() -> discord.HTTPException:
    return discord.HTTPException(HttpResponse(), "discord rejected reaction")


def cancellation_failure() -> BaseException:
    return anyio.get_cancelled_exc_class()("listener cancelled")


async def cancel_listener_at(
    cog: Nanobot,
    message: FakeMessage,
    block: BlockingCall,
) -> list[BaseException]:
    cancellations: list[BaseException] = []

    async def run_listener() -> None:
        try:
            await cog.on_message(message)
        except anyio.get_cancelled_exc_class() as error:
            cancellations.append(error)
            raise

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(run_listener)
        await block.entered.wait()
        task_group.cancel_scope.cancel()

    return cancellations


async def test_nanobot_group_remains_guild_only_administrator_scoped() -> None:
    # Given: Nanobot's remaining app-command group is still guild administration scoped.
    group = Nanobot.nanobot_group

    # When / Then: Discord receives the existing guild-only administrator metadata.
    assert group.allowed_installs.guild is True
    assert group.allowed_installs.user is False
    assert group.allowed_contexts.guild is True
    assert group.allowed_contexts.dm_channel is False
    assert group.allowed_contexts.private_channel is False
    assert group.default_permissions == discord.Permissions(administrator=True)


async def test_listener_is_registered_without_prefix_processing_override() -> None:
    # Given: a Nanobot cog is constructed with its client dependency.
    client = FakeClient(starts=[])
    cog = Nanobot(
        bot=FakeBot(),
        policy_repository=enabled_repository(),
        client=client,
    )

    # When / Then: Discord sees only an on_message listener and no process hook is called.
    assert ("on_message", cog.on_message) in cog.get_listeners()


@pytest.mark.parametrize(
    "bot, message, repository",
    ignore_cases(),
)
async def test_listener_ignores_disallowed_messages_without_client_or_prefix_calls(
    bot: FakeBot,
    message: FakeMessage,
    repository: CountingPolicyRepository,
) -> None:
    # Given: a message matches one ignore guard or fails channel policy.
    client = FakeClient(starts=[])
    cog = Nanobot(bot=bot, policy_repository=repository, client=client)

    # When: the listener receives it.
    await cog.on_message(message)

    # Then: no Discord response, SDK run, or prefix processing is triggered.
    assert message.replies == []
    assert message.sends == []
    assert client.calls == []
    assert bot.process_commands_calls == 0


async def test_listener_forwards_exact_request_and_reconstructs_final_response() -> (
    None
):
    # Given: an enabled channel mention and a client stream that produces a final answer.
    stream = EventStream([NanobotTextDelta("hel"), NanobotFinalText("hello final")])
    client = FakeClient(starts=[NanobotRunAccepted(events=stream)])
    bot = FakeBot()
    message = mention_message(
        "<@123> hello",
        author=FakeAuthor(id=30, voice=FakeVoiceState(FakeChannel(id=55))),
    )
    cog = Nanobot(bot=bot, policy_repository=enabled_repository(), client=client)

    # When: the listener handles the message.
    await cog.on_message(message)

    # Then: typing/loading happened, exact session/context was sent, and final text is safe.
    assert message.channel.typing_entries == [1]
    assert message.replies == ["…"]
    assert message.mention_author_values == [False]
    assert reconstructed_text(message) == "helhello final"
    assert stream.closed is True
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call.session_key == "discord:10:20:30"
    assert "guild_id: 10" in call.prompt
    assert "channel_id: 20" in call.prompt
    assert "author_id: 30" in call.prompt
    assert "author_voice_channel_id: 55" in call.prompt
    assert "<discord-user-message>\nhello\n</discord-user-message>" in call.prompt
    assert bot.process_commands_calls == 0


async def test_listener_keeps_typing_active_from_processing_to_success_reaction() -> (
    None
):
    # Given: an enabled mention renders successfully.
    message = mention_message()
    client = FakeClient(
        starts=[NanobotRunAccepted(events=EventStream([NanobotFinalText("done")]))]
    )
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the listener completes the full turn.
    await cog.on_message(message)

    # Then: the processing reaction is active during rendering and terminalizes to success.
    records = message.operation_trace.records
    assert [(record.name, record.emoji) for record in records] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("reply.edit", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "✅"),
        ("typing.exit", None),
    ]
    assert all(record.typing_active for record in records[1:-1])
    assert records[4].bot_user_id == 123


async def test_listener_terminalizes_public_failure_to_failure_reaction() -> None:
    # Given: the renderer emits a public failure response.
    message = mention_message()
    client = FakeClient(
        starts=[
            NanobotRunAccepted(
                events=EventStream([NanobotPublicFailure("public failure")])
            )
        ]
    )
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the listener handles the failed render outcome.
    await cog.on_message(message)

    # Then: exact response text is preserved and the source terminalizes as failed.
    assert reconstructed_text(message) == "public failure"
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("reply.edit", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]


@pytest.mark.parametrize(
    ("start", "expected"),
    (
        (
            NanobotClientBusy(session_key="discord:10:20:30"),
            "Nanobot is already handling your previous request.",
        ),
        (NanobotClientClosed(), "Nanobot is shutting down. Try again later."),
    ),
)
async def test_listener_terminalizes_start_failures_to_failure_reaction(
    start: NanobotRunStart,
    expected: str,
) -> None:
    # Given: the client returns a nominal start failure.
    message = mention_message()
    client = FakeClient(starts=[start])
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the listener handles the message.
    await cog.on_message(message)

    # Then: the existing user text is preserved and failure reactions happen while typing.
    assert message.replies == [expected]
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]


async def test_listener_terminalizes_missing_client_to_failure_reaction() -> None:
    # Given: composition has not provided a Nanobot client.
    message = mention_message()
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository())

    # When: a valid mention arrives.
    await cog.on_message(message)

    # Then: the existing config text is preserved and the turn terminalizes as failed.
    assert message.replies == ["Nanobot is not configured for this server."]
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]


async def test_listener_swallowed_rendering_failure_gets_failure_reaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the renderer raises the existing swallowed Discord rendering failure.
    message = mention_message()
    client = FakeClient(
        starts=[NanobotRunAccepted(events=EventStream([NanobotFinalText("ignored")]))]
    )
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    async def fail_render(
        responder: FakeMessage,
        stream: EventStream,
    ) -> None:
        await stream.aclose()
        raise NanobotRenderingFailure(operation="edit the response")

    monkeypatch.setattr(nanobot_module, "render_nanobot_response", fail_render)

    # When: the listener handles the failed render.
    await cog.on_message(message)

    # Then: the exception remains swallowed and the source terminalizes as failed.
    assert message.replies == []
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]


async def test_listener_cancellation_terminalizes_and_reraises() -> None:
    # Given: a blocking accepted stream is cancelled while the turn is rendering.
    stream = BlockingEventStream()
    client = FakeClient(starts=[NanobotRunAccepted(events=stream)])
    message = mention_message()
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)
    cancellations: list[BaseException] = []

    # When: caller cancellation interrupts the real listener surface.
    async def run_listener() -> None:
        try:
            await cog.on_message(message)
        except anyio.get_cancelled_exc_class() as error:
            cancellations.append(error)
            raise

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(run_listener)
        await stream.entered.wait()
        task_group.cancel_scope.cancel()

    # Then: stream cleanup happened once, cancellation propagated, and ❌ was attempted.
    assert len(cancellations) == 1
    assert stream.closed is True
    assert stream.close_count == 1
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]


async def test_listener_stream_exception_terminalizes_and_reraises_original() -> None:
    # Given: rendering starts, then the accepted stream raises an unexpected error.
    original = RuntimeError("stream exploded")
    stream = EventStream(events=[], unexpected_error=original)
    client = FakeClient(starts=[NanobotRunAccepted(events=stream)])
    message = mention_message()
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the listener observes the unexpected stream failure.
    with pytest.raises(RuntimeError) as raised:
        await cog.on_message(message)

    # Then: the original exception is preserved and the source terminalizes failed.
    assert raised.value is original
    assert stream.closed is True
    assert stream.close_count == 1
    assert message.replies == ["…"]
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]


async def test_listener_client_exception_terminalizes_and_reraises_original() -> None:
    # Given: the client raises before returning a run-start variant.
    original = RuntimeError("client exploded")
    client = FakeClient(starts=[], run_failures=[original])
    message = mention_message()
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the listener observes the unexpected client failure.
    with pytest.raises(RuntimeError) as raised:
        await cog.on_message(message)

    # Then: the original exception is preserved and the source terminalizes failed.
    assert raised.value is original
    assert message.replies == []
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]


async def test_listener_processing_add_cancellation_terminalizes_and_reraises() -> None:
    # Given: cancellation strikes while the listener adds the processing reaction.
    original = cancellation_failure()
    message = mention_message()
    message.add_reaction_failures_by_emoji["⏳"] = [original]
    client = FakeClient(
        starts=[NanobotRunAccepted(events=EventStream([NanobotFinalText("ignored")]))]
    )
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the first post-policy await receives cancellation.
    with pytest.raises(anyio.get_cancelled_exc_class()) as raised:
        await cog.on_message(message)

    # Then: failed terminalization is shield-attempted and cancellation is preserved.
    assert raised.value is original
    assert message.channel.typing_active_depth == 0
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]


async def test_listener_typing_entry_cancellation_terminalizes_and_reraises() -> None:
    # Given: cancellation strikes while entering the typing context.
    block = BlockingCall()
    message = mention_message(channel=FakeChannel(id=20, typing_enter_block=block))
    client = FakeClient(
        starts=[NanobotRunAccepted(events=EventStream([NanobotFinalText("ignored")]))]
    )
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the typing context entry is cancelled by the caller task group.
    cancellations = await cancel_listener_at(cog, message, block)

    # Then: outer cleanup attempts failed terminalization and typing depth stays zero.
    assert len(cancellations) == 1
    assert message.channel.typing_active_depth == 0
    assert message.replies == []
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter.block", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
    ]


async def test_listener_config_reply_cancellation_terminalizes_and_reraises() -> None:
    # Given: cancellation strikes while replying that Nanobot is not configured.
    original = cancellation_failure()
    message = mention_message()
    message.reply_failures.append(original)
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository())

    # When: the missing-client config reply receives cancellation.
    with pytest.raises(anyio.get_cancelled_exc_class()) as raised:
        await cog.on_message(message)

    # Then: failed terminalization is shield-attempted and cancellation is preserved.
    assert raised.value is original
    assert message.channel.typing_active_depth == 0
    assert message.replies == []
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]


async def test_listener_terminal_add_cancellation_does_not_reenter_terminalization() -> (
    None
):
    # Given: cancellation strikes while adding the successful terminal reaction.
    original = cancellation_failure()
    message = mention_message()
    message.add_reaction_failures_by_emoji["✅"] = [original]
    stream = EventStream([NanobotFinalText("done")])
    client = FakeClient(starts=[NanobotRunAccepted(events=stream)])
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: terminal reaction add receives cancellation.
    with pytest.raises(anyio.get_cancelled_exc_class()) as raised:
        await cog.on_message(message)

    # Then: terminalization is not re-entered after the terminal phase starts.
    assert raised.value is original
    assert message.channel.typing_active_depth == 0
    assert stream.close_count == 1
    assert message.replies == ["…"]
    assert reconstructed_text(message) == "done"
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("reply.edit", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "✅"),
        ("typing.exit", None),
    ]


async def test_listener_success_remove_cancellation_retries_failed_terminalization() -> (
    None
):
    # Given: cancellation strikes while removing ⏳ before a success terminal add starts.
    block = BlockingCall()
    message = mention_message()
    message.remove_reaction_blocks.append(block)
    stream = EventStream([NanobotFinalText("done")])
    client = FakeClient(starts=[NanobotRunAccepted(events=stream)])
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the first processing removal is cancelled by the caller task group.
    cancellations = await cancel_listener_at(cog, message, block)

    # Then: cleanup performs a second remove and one ❌, with no ✅ attempt.
    assert len(cancellations) == 1
    assert message.channel.typing_active_depth == 0
    assert stream.close_count == 1
    assert message.replies == ["…"]
    assert reconstructed_text(message) == "done"
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("reply.edit", None),
        ("source.remove_reaction", "⏳"),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]


async def test_listener_success_add_cancellation_does_not_reenter_terminalization() -> (
    None
):
    # Given: cancellation strikes while adding ✅ after terminal add has started.
    block = BlockingCall()
    message = mention_message()
    message.add_reaction_blocks_by_emoji["✅"] = [block]
    stream = EventStream([NanobotFinalText("done")])
    client = FakeClient(starts=[NanobotRunAccepted(events=stream)])
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the success terminal add is cancelled by the caller task group.
    cancellations = await cancel_listener_at(cog, message, block)

    # Then: there is one remove and one ✅ attempt, with no cleanup ❌.
    assert len(cancellations) == 1
    assert message.channel.typing_active_depth == 0
    assert stream.close_count == 1
    assert message.replies == ["…"]
    assert reconstructed_text(message) == "done"
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("reply.edit", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "✅"),
        ("typing.exit", None),
    ]


async def test_listener_failure_add_cancellation_does_not_reenter_terminalization() -> (
    None
):
    # Given: cancellation strikes while adding ❌ after terminal add has started.
    block = BlockingCall()
    message = mention_message()
    message.add_reaction_blocks_by_emoji["❌"] = [block]
    stream = EventStream([NanobotPublicFailure("public failure")])
    client = FakeClient(starts=[NanobotRunAccepted(events=stream)])
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the failure terminal add is cancelled by the caller task group.
    cancellations = await cancel_listener_at(cog, message, block)

    # Then: there is one remove and one ❌ attempt only.
    assert len(cancellations) == 1
    assert message.channel.typing_active_depth == 0
    assert stream.close_count == 1
    assert reconstructed_text(message) == "public failure"
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("reply.edit", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]


async def test_listener_terminal_add_exception_does_not_reenter_terminalization() -> (
    None
):
    # Given: an unexpected exception strikes while adding the terminal success reaction.
    original = RuntimeError("terminal add exploded")
    message = mention_message()
    message.add_reaction_failures_by_emoji["✅"] = [original]
    stream = EventStream([NanobotFinalText("done")])
    client = FakeClient(starts=[NanobotRunAccepted(events=stream)])
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: terminal reaction add raises after the terminal phase has started.
    with pytest.raises(RuntimeError) as raised:
        await cog.on_message(message)

    # Then: the primary error is preserved and no second terminal emoji is attempted.
    assert raised.value is original
    assert message.channel.typing_active_depth == 0
    assert stream.close_count == 1
    assert message.replies == ["…"]
    assert reconstructed_text(message) == "done"
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("reply.edit", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "✅"),
        ("typing.exit", None),
    ]


async def test_listener_cleanup_exception_preserves_primary_exception() -> None:
    # Given: the stream raises first, then failed terminalization cleanup raises too.
    primary = RuntimeError("stream exploded")
    cleanup = RuntimeError("cleanup exploded")
    message = mention_message()
    message.remove_reaction_failures.append(cleanup)
    stream = EventStream(events=[], unexpected_error=primary)
    client = FakeClient(starts=[NanobotRunAccepted(events=stream)])
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: cleanup fails while preserving an unexpected stream exception.
    with pytest.raises(RuntimeError) as raised:
        await cog.on_message(message)

    # Then: the primary exception remains raised and the cleanup error is preserved as a note.
    assert raised.value is primary
    assert "suppressed Nanobot terminalization cleanup error: cleanup exploded" in (
        primary.__notes__
    )
    assert message.channel.typing_active_depth == 0
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("source.remove_reaction", "⏳"),
        ("typing.exit", None),
    ]


async def test_listener_cleanup_exception_preserves_primary_cancellation() -> None:
    # Given: the config reply is cancelled, then failed terminalization cleanup raises too.
    primary = cancellation_failure()
    cleanup = RuntimeError("cleanup exploded")
    message = mention_message()
    message.reply_failures.append(primary)
    message.remove_reaction_failures.append(cleanup)
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository())

    # When: cleanup fails while preserving cancellation.
    with pytest.raises(anyio.get_cancelled_exc_class()) as raised:
        await cog.on_message(message)

    # Then: the cancellation object remains raised and the cleanup error is preserved.
    assert raised.value is primary
    assert "suppressed Nanobot terminalization cleanup error: cleanup exploded" in (
        primary.__notes__
    )
    assert message.channel.typing_active_depth == 0
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.reply", None),
        ("source.remove_reaction", "⏳"),
        ("typing.exit", None),
    ]


async def test_listener_source_and_client_share_lifecycle_trace() -> None:
    # Given: source message and fake client write to the same operation trace.
    message = mention_message()
    client = FakeClient(
        starts=[NanobotRunAccepted(events=EventStream([NanobotFinalText("done")]))],
        operation_trace=message.operation_trace,
    )
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the listener completes a successful turn.
    await cog.on_message(message)

    # Then: client.run occurs between processing add and render while typing is active.
    records = message.operation_trace.records
    assert [(record.name, record.emoji) for record in records] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("client.run", None),
        ("source.reply", None),
        ("reply.edit", None),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "✅"),
        ("typing.exit", None),
    ]
    assert all(record.typing_active for record in records[1:-1])


async def test_listener_terminalizes_rendering_failure_when_processing_add_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: the renderer raises the existing swallowed failure and ⏳ add fails.
    message = mention_message()
    message.add_reaction_failures.append(http_failure())
    client = FakeClient(
        starts=[NanobotRunAccepted(events=EventStream([NanobotFinalText("ignored")]))]
    )
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    async def fail_render(
        responder: FakeMessage,
        stream: EventStream,
    ) -> None:
        await stream.aclose()
        raise NanobotRenderingFailure(operation="edit the response")

    monkeypatch.setattr(nanobot_module, "render_nanobot_response", fail_render)

    # When: processing reaction add is rejected by Discord.
    with caplog.at_level("WARNING", logger=nanobot_module.logger.name):
        await cog.on_message(message)

    # Then: rendering failure is still swallowed and the HTTP rejection is logged only.
    assert message.replies == []
    assert [
        (record.name, record.emoji) for record in message.operation_trace.records
    ] == [
        ("typing.enter", None),
        ("source.add_reaction", "⏳"),
        ("source.remove_reaction", "⏳"),
        ("source.add_reaction", "❌"),
        ("typing.exit", None),
    ]
    assert [record.message for record in caplog.records] == [
        "Discord rejected Nanobot reaction add"
    ]


@pytest.mark.parametrize(
    ("failure_phase", "expected_log"),
    (
        ("processing-add", "Discord rejected Nanobot reaction add"),
        ("processing-remove", "Discord rejected Nanobot reaction removal"),
        ("terminal-add", "Discord rejected Nanobot reaction add"),
    ),
)
async def test_listener_reaction_http_failures_preserve_successful_render(
    failure_phase: str,
    expected_log: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: a successful render and one injected Discord reaction HTTP failure.
    message = mention_message()
    match failure_phase:
        case "processing-add":
            message.add_reaction_failures.append(http_failure())
        case "processing-remove":
            message.remove_reaction_failures.append(http_failure())
        case "terminal-add":
            message.add_reaction_failures_by_emoji["✅"] = [http_failure()]
        case unreachable:
            assert_never(unreachable)
    client = FakeClient(
        starts=[NanobotRunAccepted(events=EventStream([NanobotFinalText("done")]))]
    )
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: Discord rejects exactly that reaction operation.
    with caplog.at_level("WARNING", logger=nanobot_module.logger.name):
        await cog.on_message(message)

    # Then: the reply/render outcome is unchanged and only the reaction failure is logged.
    assert message.replies == ["…"]
    assert reconstructed_text(message) == "done"
    assert [record.message for record in caplog.records] == [expected_log]


async def test_listener_reaction_http_failure_preserves_stream_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: an unexpected stream error and a rejected terminal ❌ add.
    original = RuntimeError("stream exploded")
    message = mention_message()
    message.add_reaction_failures_by_emoji["❌"] = [http_failure()]
    stream = EventStream(events=[], unexpected_error=original)
    client = FakeClient(starts=[NanobotRunAccepted(events=stream)])
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: both the stream and terminal reaction fail.
    with caplog.at_level("WARNING", logger=nanobot_module.logger.name):
        with pytest.raises(RuntimeError) as raised:
            await cog.on_message(message)

    # Then: the stream exception remains the raised error and the HTTP failures are logged.
    assert raised.value is original
    assert stream.closed is True
    assert stream.close_count == 1
    assert message.replies == ["…"]
    assert [record.message for record in caplog.records] == [
        "Discord rejected Nanobot reaction add"
    ]


async def test_listener_ignored_message_does_not_touch_typing_or_reactions() -> None:
    # Given: a valid-looking mention is disallowed by policy.
    message = mention_message(channel=FakeChannel(id=21))
    client = FakeClient(starts=[])
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the listener rejects it before processing.
    await cog.on_message(message)

    # Then: the source message remains untouched.
    assert message.operation_trace.records == []
    assert message.replies == []
    assert client.calls == []


async def test_thread_parent_policy_allows_thread_session_identity() -> None:
    # Given: only the parent channel is allowed by policy.
    parent = FakeChannel(id=40)
    thread = FakeChannel(id=44, parent=parent)
    stream = EventStream([NanobotFinalText("thread final")])
    client = FakeClient(starts=[NanobotRunAccepted(events=stream)])
    message = mention_message(channel=thread)
    cog = Nanobot(
        bot=FakeBot(),
        policy_repository=enabled_repository(channel_id="40"),
        client=client,
    )

    # When: the listener receives a thread mention.
    await cog.on_message(message)

    # Then: parent policy is honored while session/context keep the actual thread.
    assert client.calls[0].session_key == "discord:10:44:30"
    assert "channel_id: 44" in client.calls[0].prompt
    assert reconstructed_text(message) == "thread final"


@pytest.mark.parametrize(
    "start, expected",
    start_failures(),
)
async def test_listener_sends_safe_deterministic_start_failures(
    start: NanobotRunStart,
    expected: str,
) -> None:
    # Given: the client cannot start the requested run.
    client = FakeClient(starts=[start])
    message = mention_message()
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: the listener handles an otherwise valid mention.
    await cog.on_message(message)

    # Then: the public response is deterministic and contains no private detail.
    assert message.replies == [expected]
    assert "discord:" not in message.replies[0]


async def test_listener_reports_missing_client_as_safe_config_response() -> None:
    # Given: composition has not provided a Nanobot client.
    message = mention_message()
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository())

    # When: a valid mention arrives.
    await cog.on_message(message)

    # Then: users see only a stable configuration message.
    assert message.replies == ["Nanobot is not configured for this server."]


async def test_different_sessions_can_run_while_duplicate_session_is_busy() -> None:
    # Given: one active stream blocks, then duplicate and different-session starts are queued.
    active_stream = BlockingEventStream()
    other_stream = EventStream([NanobotFinalText("other final")])
    client = FakeClient(
        starts=[
            NanobotRunAccepted(events=active_stream),
            NanobotClientBusy(session_key="discord:10:20:30"),
            NanobotRunAccepted(events=other_stream),
        ]
    )
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)
    active = mention_message()
    duplicate = mention_message()
    other = mention_message(author=FakeAuthor(id=31))

    # When: the active session blocks, a duplicate is rejected, and another session runs.
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(cog.on_message, active)
        await active_stream.entered.wait()
        await cog.on_message(duplicate)
        await cog.on_message(other)
        active_stream.release.set()

    # Then: duplicate got busy while a different session completed concurrently.
    assert duplicate.replies == ["Nanobot is already handling your previous request."]
    assert reconstructed_text(other) == "other final"
    assert [call.session_key for call in client.calls] == [
        "discord:10:20:30",
        "discord:10:20:30",
        "discord:10:20:31",
    ]


async def test_cog_close_is_idempotent_and_owns_passed_client() -> None:
    # Given: the cog owns a passed client instance.
    client = FakeClient(starts=[])
    cog = Nanobot(bot=FakeBot(), policy_repository=enabled_repository(), client=client)

    # When: composition closes the cog repeatedly.
    await cog.aclose()
    await cog.aclose()

    # Then: the underlying client is closed exactly once.
    assert client.close_count == 1


async def test_manual_qa_fake_discord_listener_surfaces() -> None:
    # Given: the requested fake Discord listener matrix and deterministic client outputs.
    active_stream = BlockingEventStream()
    client = FakeClient(
        starts=[
            NanobotRunAccepted(events=EventStream([NanobotFinalText("enabled final")])),
            NanobotRunAccepted(events=active_stream),
            NanobotClientBusy(session_key="discord:10:20:30"),
        ]
    )
    bot = FakeBot()
    cog = Nanobot(bot=bot, policy_repository=enabled_repository(), client=client)
    enabled = mention_message()
    skipped = manual_blocked_messages()
    active = mention_message()
    duplicate = mention_message()

    # When: the real listener handles enabled, blocked, and duplicate-active cases.
    await cog.on_message(enabled)
    disabled_cog = Nanobot(
        bot=bot,
        policy_repository=disabled_repository(),
        client=client,
    )
    await disabled_cog.on_message(skipped[0])
    for message in skipped[1:]:
        await cog.on_message(message)
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(cog.on_message, active)
        await active_stream.entered.wait()
        await cog.on_message(duplicate)
        active_stream.release.set()

    # Then: observable output proves no blocked path calls SDK or process_commands.
    blocked_reply_counts = [len(message.replies) for message in skipped]
    print(f"enabled_reply_count={len(enabled.replies)}")
    print(f"enabled_text={reconstructed_text(enabled)}")
    print(f"blocked_reply_counts={blocked_reply_counts}")
    print(f"duplicate_text={duplicate.replies[-1]}")
    print(f"client_calls={len(client.calls)}")
    print(f"process_commands_calls={bot.process_commands_calls}")
    assert len(enabled.replies) == 1
    assert reconstructed_text(enabled) == "enabled final"
    assert blocked_reply_counts == [0, 0, 0, 0, 0, 0]
    assert duplicate.replies == ["Nanobot is already handling your previous request."]
    assert len(client.calls) == 3
    assert bot.process_commands_calls == 0
