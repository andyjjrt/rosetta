from types import SimpleNamespace

import discord
import pytest

from rosetta.models.music import PlayRequest
from rosetta.utils import music_service
from rosetta.utils.music_service import MusicService
from tests.music_service_fakes import (
    CHANNEL_ID,
    URL,
    USER_ID,
    FakeBot,
    FakeChatChannel,
    FakeGuild,
    FakeMember,
    FakeNode,
    FakePlayer,
    FakePool,
    FakeVoiceChannel,
    permissions,
    track,
    voice_state,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def voice_channel_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(music_service.discord, "VoiceChannel", FakeVoiceChannel)


@pytest.mark.parametrize(
    ("voice_state_name", "channel_permissions", "expected"),
    [
        (None, permissions(), "user_not_in_channel"),
        ("disconnected", permissions(), "user_not_in_channel"),
        ("same", permissions(connect=False), "bot_permission_denied"),
        ("same", permissions(speak=False), "bot_permission_denied"),
    ],
)
async def test_play_validates_target_before_side_effects(
    voice_state_name: str | None, channel_permissions: SimpleNamespace, expected: str
) -> None:
    guild = FakeGuild(10)
    chat_channel = FakeChatChannel(int(CHANNEL_ID), guild)
    voice_channel = FakeVoiceChannel(21, guild, channel_permissions)
    if voice_state_name == "disconnected":
        guild.members[int(USER_ID)] = FakeMember(
            int(USER_ID), SimpleNamespace(channel=None)
        )
    if voice_state_name == "same":
        guild.members[int(USER_ID)] = FakeMember(
            int(USER_ID), voice_state(voice_channel)
        )
    node = FakeNode("MAIN", [track("song", URL)])
    pool = FakePool([node])

    result = await MusicService(FakeBot(chat_channel), pool).play(
        PlayRequest(user_id=USER_ID, chat_channel_id=CHANNEL_ID, url=URL)
    )

    assert result.status == "failure"
    assert result.code == expected
    assert (voice_channel.connect_calls, pool.destroy_calls, node.searches) == (
        0,
        [],
        [],
    )


async def test_play_uses_fetched_members_voice_channel_as_target() -> None:
    guild = FakeGuild(10)
    chat_channel = FakeChatChannel(int(CHANNEL_ID), guild)
    voice_channel = FakeVoiceChannel(21, guild, permissions())
    guild.fetched_members[int(USER_ID)] = FakeMember(
        int(USER_ID), voice_state(voice_channel)
    )
    node = FakeNode("MAIN", [track("song", URL)])
    voice_channel.next_player = FakePlayer(node, voice_channel, register=False)
    pool = FakePool([node])

    result = await MusicService(FakeBot(chat_channel), pool).play(
        PlayRequest(user_id=USER_ID, chat_channel_id=CHANNEL_ID, url=URL)
    )

    assert result.status == "success"
    assert voice_channel.id != int(CHANNEL_ID)
    assert guild.get_member_calls == [int(USER_ID)]
    assert guild.fetch_member_calls == [int(USER_ID)]
    assert voice_channel.permission_calls == 1
    assert (voice_channel.connect_calls, pool.destroy_calls, node.searches) == (
        1,
        [10],
        [URL],
    )


async def test_play_fetches_uncached_chat_channel_before_resolving_guild() -> None:
    guild = FakeGuild(10)
    chat_channel = FakeChatChannel(int(CHANNEL_ID), guild)
    voice_channel = FakeVoiceChannel(21, guild, permissions())
    guild.members[int(USER_ID)] = FakeMember(int(USER_ID), voice_state(voice_channel))
    node = FakeNode("MAIN", [track("song", URL)])
    voice_channel.next_player = FakePlayer(node, voice_channel, register=False)
    pool = FakePool([node])
    bot = FakeBot(None, fetched_channel=chat_channel)

    result = await MusicService(bot, pool).play(
        PlayRequest(user_id=USER_ID, chat_channel_id=CHANNEL_ID, url=URL)
    )

    assert result.status == "success"
    assert (bot.get_calls, bot.fetch_calls) == (1, 1)
    assert guild.get_member_calls == [int(USER_ID)]
    assert voice_channel.connect_calls == 1


async def test_play_maps_fetch_member_not_found_before_side_effects() -> None:
    error = discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "missing")
    guild = FakeGuild(10, fetch_error=error)
    chat_channel = FakeChatChannel(int(CHANNEL_ID), guild)
    voice_channel = FakeVoiceChannel(21, guild, permissions())
    node = FakeNode("MAIN", [track("song", URL)])
    pool = FakePool([node])

    result = await MusicService(FakeBot(chat_channel), pool).play(
        PlayRequest(user_id=USER_ID, chat_channel_id=CHANNEL_ID, url=URL)
    )

    assert result.status == "failure"
    assert result.code == "user_not_in_channel"
    assert (voice_channel.connect_calls, pool.destroy_calls, node.searches) == (
        0,
        [],
        [],
    )


@pytest.mark.parametrize("error_type", [discord.Forbidden, discord.HTTPException])
async def test_play_keeps_fetch_member_http_errors_unhidden(
    error_type: type[discord.HTTPException],
) -> None:
    error = error_type(SimpleNamespace(status=403, reason="Forbidden"), "forbidden")
    guild = FakeGuild(10, fetch_error=error)
    chat_channel = FakeChatChannel(int(CHANNEL_ID), guild)
    voice_channel = FakeVoiceChannel(21, guild, permissions())
    node = FakeNode("MAIN", [track("song", URL)])
    pool = FakePool([node])

    with pytest.raises(error_type):
        await MusicService(FakeBot(chat_channel), pool).play(
            PlayRequest(user_id=USER_ID, chat_channel_id=CHANNEL_ID, url=URL)
        )

    assert (voice_channel.connect_calls, pool.destroy_calls, node.searches) == (
        0,
        [],
        [],
    )


async def test_play_rejects_chat_channel_without_guild_before_member_lookup() -> None:
    chat_channel = FakeChatChannel(int(CHANNEL_ID), None)
    node = FakeNode("MAIN", [track("song", URL)])
    pool = FakePool([node])

    result = await MusicService(FakeBot(chat_channel), pool).play(
        PlayRequest(user_id=USER_ID, chat_channel_id=CHANNEL_ID, url=URL)
    )

    assert result.status == "failure"
    assert result.code == "channel_not_found"
    assert (pool.destroy_calls, node.searches) == ([], [])
