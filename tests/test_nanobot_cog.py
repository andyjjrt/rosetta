from __future__ import annotations

import anyio
import discord
import pytest

from rosetta.commands.nanobot import Nanobot
from rosetta.utils.nanobot_client import (
    NanobotClientBusy,
    NanobotRunAccepted,
    NanobotRunStart,
)
from rosetta.utils.nanobot_response import NanobotFinalText, NanobotTextDelta
from rosetta.utils.views.Nanobot import NanobotSettingsView
from tests.nanobot_cog_fakes import (
    BlockingEventStream,
    CountingPolicyRepository,
    EventStream,
    FakeAuthor,
    FakeBot,
    FakeChannel,
    FakeClient,
    FakeGuild,
    FakeInteraction,
    FakeMessage,
    FakePermissions,
    FakeUser,
    FakeVoiceState,
    disabled_repository,
    enabled_repository,
    ignore_cases,
    manual_blocked_messages,
    mention_message,
    mention_policy_is_none,
    reconstructed_text,
    settings_denials,
    start_failures,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_settings_registration_and_admin_view_behavior_remain_intact() -> None:
    # Given: Todo 6 registered the Nanobot settings app-command surface.
    repository = CountingPolicyRepository()
    cog = Nanobot(bot=None, policy_repository=repository)
    interaction = FakeInteraction(
        guild=FakeGuild(id=10),
        user=FakeUser(id=99),
        permissions=FakePermissions(administrator=True),
    )

    # When: an administrator opens /nanobot settings.
    await cog.settings.callback(cog, interaction)

    # Then: registration metadata, repository access, and safe ephemeral view remain intact.
    group = Nanobot.nanobot_group
    sent = interaction.response.sent[-1]
    assert group.allowed_installs.guild is True
    assert group.allowed_installs.user is False
    assert group.allowed_contexts.guild is True
    assert group.allowed_contexts.dm_channel is False
    assert group.allowed_contexts.private_channel is False
    assert group.default_permissions == discord.Permissions(administrator=True)
    assert repository.calls == 1
    assert sent.ephemeral is True
    assert isinstance(sent.view, NanobotSettingsView)
    assert mention_policy_is_none(sent.allowed_mentions)
    assert sent.content is not None
    assert "Nanobot settings" in sent.content


@pytest.mark.parametrize(
    "interaction, expected",
    settings_denials(),
)
async def test_settings_runtime_denial_remains_before_repository_access(
    interaction: FakeInteraction,
    expected: str,
) -> None:
    # Given: a settings invocation is not both guild-scoped and administrator-authorized.
    repository = CountingPolicyRepository()
    cog = Nanobot(bot=None, policy_repository=repository)

    # When: the settings command callback runs.
    await cog.settings.callback(cog, interaction)

    # Then: denial is ephemeral and repository state remains unread.
    sent = interaction.response.sent[-1]
    assert repository.calls == 0
    assert sent.ephemeral is True
    assert sent.content is not None
    assert expected in sent.content


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
