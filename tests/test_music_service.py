from types import SimpleNamespace

import discord
import pytest
from lava_lyra.exceptions import NodeNotAvailable, NodeRestException
from pydantic import ValidationError

from rosetta.models.music import LoopModeName, PlayRequest
from rosetta.utils import music_service
from rosetta.utils.music_service import MusicService
from tests.music_service_fakes import (
    CHANNEL_ID,
    URL,
    USER_ID,
    FakeBot,
    FakeNode,
    FakePlayer,
    FakePool,
    FakeVoiceChannel,
    make_target,
    permissions,
    playlist,
    track,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def voice_channel_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(music_service.discord, "VoiceChannel", FakeVoiceChannel)


async def test_search_maps_limits_and_backend_failures() -> None:
    service = MusicService(
        FakeBot(None),
        FakePool([FakeNode("MAIN", [track("one", "u1"), track("two", "u2")])]),
    )
    result = await service.search(" query ", 1)
    assert result.status == "success"
    assert [(item.title, item.duration_ms) for item in result.tracks] == [("one", 1234)]

    for backend_error in (NodeNotAvailable("down"), NodeRestException("down")):
        failure = await MusicService(
            FakeBot(None), FakePool([FakeNode("MAIN", backend_error)])
        ).search("query", 10)
        assert failure.status == "failure"
        assert failure.code == "music_backend_unavailable"

    backend = await MusicService(FakeBot(None), FakePool([])).search("query", 10)
    assert backend.status == "failure"
    assert backend.code == "music_backend_unavailable"


def test_boundary_models_reject_non_ascii_snowflakes_and_bad_limits() -> None:
    for field, value in (("user_id", "12x"), ("voice_channel_id", "١٢")):
        payload = {"user_id": "123", "voice_channel_id": "456", "url": "https://track"}
        payload[field] = value
        with pytest.raises(ValidationError):
            PlayRequest.model_validate(payload)
    for limit in (0, 26):
        with pytest.raises(ValidationError):
            MusicService(FakeBot(None), FakePool([FakeNode("MAIN", [])])).parse_search(
                keyword="x", limit=limit
            )


async def test_play_starts_valid_target_and_preserves_normalization() -> None:
    service, _, node, channel = make_target(
        [track("song", "https://song", thumbnail="thumb")]
    )
    channel.next_player = FakePlayer(node, channel, register=False)
    result = await service.play(
        PlayRequest(user_id=USER_ID, voice_channel_id=CHANNEL_ID, url="https://song")
    )
    assert result.status == "success"
    assert result.playback_status == "started"
    assert result.enqueued_count == 1
    assert channel.next_player.volume_calls == [20]
    assert channel.next_player.filter_payloads == ["play-normalization"]
    assert channel.next_player.played[0].uri == "https://song"


async def test_play_preserves_playlist_top_shuffle_loop_when_queueing() -> None:
    tracks = playlist([track("a", "u1"), track("b", "u2")])
    service, _, node, channel = make_target(tracks)
    player = FakePlayer(node, channel)
    player.is_playing = True
    channel.next_player = player
    request = PlayRequest(
        user_id=USER_ID,
        voice_channel_id=CHANNEL_ID,
        url=URL,
        loop=LoopModeName.QUEUE,
        shuffle=True,
        top=True,
    )
    result = await service.play(request)
    assert result.status == "success"
    assert result.playback_status == "queued"
    assert result.enqueued_count == 2
    assert (
        player.queue.front,
        player.queue.shuffled,
        player.queue.loop_name,
        player.played,
    ) == (True, True, "QUEUE", [])


async def test_play_reuses_same_channel_and_conflicts_on_different_channel() -> None:
    service, pool, node, channel = make_target([track("song", URL)])
    player = FakePlayer(node, channel)
    reused = await service.play(
        PlayRequest(user_id=USER_ID, voice_channel_id=CHANNEL_ID, url=URL)
    )
    assert reused.status == "success"
    assert (channel.connect_calls, player.lookup_queries) == (0, [URL])

    node.players[channel.guild.id] = FakePlayer(
        node, FakeVoiceChannel(21, channel.guild, permissions())
    )
    conflict = await service.play(
        PlayRequest(user_id=USER_ID, voice_channel_id=CHANNEL_ID, url=URL)
    )
    assert conflict.status == "failure"
    assert conflict.code == "player_channel_conflict"
    assert (channel.connect_calls, pool.destroy_calls) == (0, [])


@pytest.mark.parametrize(
    ("channel", "expected"),
    [(None, "channel_not_found"), ("text", "not_voice_channel")],
)
async def test_play_rejects_missing_or_non_voice_channel_before_side_effects(
    channel: str | None, expected: str
) -> None:
    node = FakeNode("MAIN", [track("song", URL)])
    result = await MusicService(FakeBot(channel), FakePool([node])).play(
        PlayRequest(user_id=USER_ID, voice_channel_id=CHANNEL_ID, url=URL)
    )
    assert result.status == "failure"
    assert result.code == expected
    assert node.searches == []


async def test_play_returns_node_not_found_before_connect() -> None:
    service, _, _, channel = make_target([])
    result = await service.play(
        PlayRequest(
            user_id=USER_ID, voice_channel_id=CHANNEL_ID, url=URL, node_name="missing"
        )
    )
    assert result.status == "failure"
    assert result.code == "node_not_found"
    assert channel.connect_calls == 0


async def test_play_without_nodes_returns_backend_unavailable_before_target_resolution() -> (
    None
):
    bot = FakeBot(None)
    pool = FakePool([])
    result = await MusicService(bot, pool).play(
        PlayRequest(user_id=USER_ID, voice_channel_id=CHANNEL_ID, url=URL)
    )
    assert result.status == "failure"
    assert result.code == "music_backend_unavailable"
    assert (bot.get_calls, bot.fetch_calls, pool.destroy_calls) == (0, 0, [])


async def test_play_missing_explicit_node_returns_node_not_found_before_target_resolution() -> (
    None
):
    bot = FakeBot(None)
    pool = FakePool([FakeNode("MAIN", [])])
    result = await MusicService(bot, pool).play(
        PlayRequest(
            user_id=USER_ID, voice_channel_id=CHANNEL_ID, url=URL, node_name="missing"
        )
    )
    assert result.status == "failure"
    assert result.code == "node_not_found"
    assert (bot.get_calls, bot.fetch_calls, pool.destroy_calls) == (0, 0, [])


async def test_play_maps_fetch_channel_not_found_before_side_effects() -> None:
    error = discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "missing")
    bot = FakeBot(None, fetch_error=error)
    node = FakeNode("MAIN", [track("song", URL)])
    pool = FakePool([node])
    result = await MusicService(bot, pool).play(
        PlayRequest(user_id=USER_ID, voice_channel_id=CHANNEL_ID, url=URL)
    )
    assert result.status == "failure"
    assert result.code == "channel_not_found"
    assert (bot.get_calls, bot.fetch_calls, pool.destroy_calls, node.searches) == (
        1,
        1,
        [],
        [],
    )


async def test_play_returns_lookup_failures_without_volume_filter_queue_or_play_mutation() -> (
    None
):
    for tracks, expected in (
        ([], "no_tracks_found"),
        (NodeNotAvailable("down"), "music_backend_unavailable"),
    ):
        service, _, node, channel = make_target(tracks)
        channel.next_player = FakePlayer(node, channel)
        result = await service.play(
            PlayRequest(user_id=USER_ID, voice_channel_id=CHANNEL_ID, url="missing")
        )
        assert result.status == "failure"
        assert result.code == expected
        assert (
            channel.next_player.volume_calls,
            channel.next_player.filter_payloads,
        ) == ([], [])
        assert (channel.next_player.queue.items, channel.next_player.played) == ([], [])
