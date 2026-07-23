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
        ("other", permissions(), "user_not_in_channel"),
        ("same", permissions(connect=False), "bot_permission_denied"),
    ],
)
async def test_play_validates_target_before_side_effects(
    voice_state_name: str | None, channel_permissions: SimpleNamespace, expected: str
) -> None:
    guild = FakeGuild(10)
    requested = FakeVoiceChannel(int(CHANNEL_ID), guild, channel_permissions)
    if voice_state_name == "disconnected":
        guild.members[int(USER_ID)] = FakeMember(
            int(USER_ID), SimpleNamespace(channel=None)
        )
    if voice_state_name == "same":
        guild.members[int(USER_ID)] = FakeMember(int(USER_ID), voice_state(requested))
    if voice_state_name == "other":
        guild.members[int(USER_ID)] = FakeMember(
            int(USER_ID), voice_state(FakeVoiceChannel(21, guild, permissions()))
        )
    node = FakeNode("MAIN", [track("song", URL)])
    pool = FakePool([node])

    result = await MusicService(FakeBot(requested), pool).play(
        PlayRequest(user_id=USER_ID, voice_channel_id=CHANNEL_ID, url=URL)
    )

    assert result.status == "failure"
    assert result.code == expected
    assert (requested.connect_calls, pool.destroy_calls, node.searches) == (0, [], [])


async def test_play_fetches_uncached_member_and_starts_when_voice_matches() -> None:
    guild = FakeGuild(10)
    requested = FakeVoiceChannel(int(CHANNEL_ID), guild, permissions())
    guild.fetched_members[int(USER_ID)] = FakeMember(
        int(USER_ID), voice_state(requested)
    )
    node = FakeNode("MAIN", [track("song", URL)])
    requested.next_player = FakePlayer(node, requested, register=False)
    pool = FakePool([node])

    result = await MusicService(FakeBot(requested), pool).play(
        PlayRequest(user_id=USER_ID, voice_channel_id=CHANNEL_ID, url=URL)
    )

    assert result.status == "success"
    assert guild.get_member_calls == [int(USER_ID)]
    assert guild.fetch_member_calls == [int(USER_ID)]
    assert (requested.connect_calls, pool.destroy_calls, node.searches) == (
        1,
        [10],
        [URL],
    )


async def test_play_maps_fetch_member_not_found_before_side_effects() -> None:
    error = discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "missing")
    guild = FakeGuild(10, fetch_error=error)
    requested = FakeVoiceChannel(int(CHANNEL_ID), guild, permissions())
    node = FakeNode("MAIN", [track("song", URL)])
    pool = FakePool([node])

    result = await MusicService(FakeBot(requested), pool).play(
        PlayRequest(user_id=USER_ID, voice_channel_id=CHANNEL_ID, url=URL)
    )

    assert result.status == "failure"
    assert result.code == "user_not_in_channel"
    assert (requested.connect_calls, pool.destroy_calls, node.searches) == (0, [], [])


@pytest.mark.parametrize("error_type", [discord.Forbidden, discord.HTTPException])
async def test_play_keeps_fetch_member_http_errors_unhidden(
    error_type: type[discord.HTTPException],
) -> None:
    error = error_type(SimpleNamespace(status=403, reason="Forbidden"), "forbidden")
    guild = FakeGuild(10, fetch_error=error)
    requested = FakeVoiceChannel(int(CHANNEL_ID), guild, permissions())
    node = FakeNode("MAIN", [track("song", URL)])
    pool = FakePool([node])

    with pytest.raises(error_type):
        await MusicService(FakeBot(requested), pool).play(
            PlayRequest(user_id=USER_ID, voice_channel_id=CHANNEL_ID, url=URL)
        )

    assert (requested.connect_calls, pool.destroy_calls, node.searches) == (0, [], [])
