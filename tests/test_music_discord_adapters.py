from types import SimpleNamespace

import pytest
from discord.ext import commands

from rosetta.commands import music as music_module
from rosetta.commands.music import Music
from rosetta.models.music import (
    MusicErrorCode,
    MusicFailure,
    PlayRequest,
    SearchSuccess,
    TrackSummary,
)
from rosetta.utils.views.Search import SearchView
from tests.music_discord_fakes import (
    FakeGuild,
    FakeInteraction,
    FakePlayer,
    FakePool,
    FakeService,
    FakeUser,
    FakeVoiceChannel,
    FakeVoiceState,
    music_cog,
    summary,
    track,
)

pytestmark = pytest.mark.anyio


def test_music_cog_public_registration_contract() -> None:
    assert Music.__name__ == "Music"
    assert Music.play.name == "play"
    assert Music.search.name == "search"
    assert Music.loop_command.name == "loop"
    assert Music.shuffle.name == "shuffle"
    assert Music.skip.name == "skip"
    assert Music.leave.name == "leave"
    assert Music.nowplaying.name == "nowplaying"
    assert Music.switchnode.name == "switchnode"
    assert Music.reload_nodes.name == "reload_nodes"
    assert {choice.value for choice in Music.play._params["loop"].choices} == {
        "Off",
        "One",
        "Queue",
    }
    assert str(Music.play._params["shuffle"].description) == "shuffle the playlist"
    assert str(Music.play._params["top"].description) == "add to the top of queue"


async def test_play_command_preserves_defer_followup_embed_options() -> None:
    song = track("Song")
    pool = FakePool([song])
    music = music_cog(pool)
    node = SimpleNamespace(_identifier="MAIN")
    player = FakePlayer(node, [song])
    guild = FakeGuild()
    channel = FakeVoiceChannel(guild, player)
    interaction = FakeInteraction(FakeUser(FakeVoiceState(channel)), guild)

    await Music.play.callback(
        music,
        interaction,
        "https://track.example/song",
        "Queue",
        True,
        True,
        "MAIN",
    )

    assert interaction.response.deferred is True
    assert interaction.followup.wait_values == [True]
    assert (
        interaction.followup.sent_embeds[0].title
        == ":globe_with_meridians:   Processing"
    )
    edited = interaction.message.edited_embeds[0]
    assert edited.description == "Enqueued [**Song**](https://track.example/song)"
    assert edited.footer.text == "tester • MAIN"
    assert edited.thumbnail.url == "https://track.example/thumb.jpg"
    assert pool.destroy_calls == [guild.id]
    assert player.lookup_queries == ["https://track.example/song"]
    assert player.queue.front is True
    assert player.queue.shuffled is True
    assert player.queue.loop == music_module.LoopMode.QUEUE
    assert player.played == [song]


async def test_search_command_preserves_defer_followup_view_and_selected_uri() -> None:
    song = track("Result", "https://track.example/result")
    pool = FakePool([song])
    music = music_cog(pool)
    music.bot.cogs = {"Music": music}
    interaction = FakeInteraction(FakeUser(None), FakeGuild())

    await Music.search.callback(music, interaction, "lofi")

    assert interaction.response.deferred is True
    assert pool.searches == ["lofi"]
    view = interaction.followup.sent_views[0]
    assert view.keyword == "lofi"
    assert view.tracks == [
        TrackSummary(
            title="Result",
            author="artist",
            duration_ms=125_000,
            uri="https://track.example/result",
            thumbnail="https://track.example/thumb.jpg",
        )
    ]

    selection = FakeInteraction(
        FakeUser(
            FakeVoiceState(
                FakeVoiceChannel(
                    FakeGuild(), FakePlayer(SimpleNamespace(_identifier="MAIN"), [song])
                )
            )
        )
    )
    selection.data = {"values": ["https://selected.example/track"]}
    seen_urls: list[str] = []

    async def fake_play(
        selected_interaction: FakeInteraction,
        url: str,
        loop: str = "Off",
        shuffle: bool = False,
        top: bool = False,
        node_name: str | None = None,
    ) -> music_module.discord.Embed:
        seen_urls.append(url)
        return music_module.SuccessEmbed(selection.user, "selected")

    music._play = fake_play
    await view.select_callback()(selection)

    assert seen_urls == ["https://selected.example/track"]
    assert selection.response.sent_embeds[0].description == "selected"


def test_search_view_renders_track_rows_options_pagination_and_time() -> None:
    tracks = [
        track(f"Song {index}", f"https://track.example/{index}") for index in range(6)
    ]
    view = SearchView(SimpleNamespace(cogs={}), "query", tracks)

    assert view._format_time(125_000) == "02:05"
    assert len(view.tracks) == 6
    assert view.page_size == 5
    assert view.container.children[0].content == '🔍 **Search result of "query"'
    first_page_text = view.container.children[2].children[0].content
    assert first_page_text == "1. [Song 0](https://track.example/0) `02:05`"
    select = view.container.children[-2].children[0]
    assert [option.value for option in select.options] == [
        "https://track.example/0",
        "https://track.example/1",
        "https://track.example/2",
        "https://track.example/3",
        "https://track.example/4",
    ]


async def test_search_command_delegates_to_service_and_view_renders_summaries() -> None:
    service = FakeService(SearchSuccess(tracks=(summary("Service Result"),)))
    music = music_cog(FakePool([]))
    music.service = service
    interaction = FakeInteraction(FakeUser(None), FakeGuild())

    await Music.search.callback(music, interaction, "shared logic")

    assert service.search_calls == [("shared logic", 10)]
    view = interaction.followup.sent_views[0]
    assert view.tracks == list(service.search_result.tracks)
    assert view.container.children[2].children[0].content == (
        "1. [Service Result](https://summary.example/song) `02:05`"
    )


async def test_play_adapter_delegates_enqueue_options_and_keeps_success_embed() -> None:
    service = FakeService(SearchSuccess(tracks=()))
    music = music_cog(FakePool([]))
    music.service = service
    node = SimpleNamespace(_identifier="MAIN")
    player = FakePlayer(node, [])
    guild = FakeGuild()
    channel = FakeVoiceChannel(guild, player)
    player.channel = channel
    interaction = FakeInteraction(FakeUser(FakeVoiceState(channel)), guild)

    embed = await music._play(
        interaction,
        "https://request.example/song",
        "Queue",
        True,
        True,
        "MAIN",
    )

    assert service.enqueue_calls == [
        (
            player,
            PlayRequest(
                user_id="30",
                chat_channel_id="40",
                url="https://request.example/song",
                loop="Queue",
                shuffle=True,
                top=True,
                node_name="MAIN",
            ),
        )
    ]
    assert (
        embed.description == "Enqueued [**Service Song**](https://service.example/song)"
    )
    assert embed.footer.text == "tester • MAIN"
    assert embed.thumbnail.url == "https://service.example/thumb.jpg"


async def test_play_adapter_maps_expected_service_failure_to_command_error() -> None:
    service = FakeService(SearchSuccess(tracks=()))
    service.enqueue_result = MusicFailure(
        code=MusicErrorCode.NO_TRACKS_FOUND,
        message="No tracks were found.",
    )
    music = music_cog(FakePool([]))
    music.service = service
    guild = FakeGuild()
    channel = FakeVoiceChannel(
        guild, FakePlayer(SimpleNamespace(_identifier="MAIN"), [])
    )
    interaction = FakeInteraction(FakeUser(FakeVoiceState(channel)), guild)

    with pytest.raises(
        commands.CommandError, match="No results were found for that search term."
    ):
        await music._play(interaction, "missing")
    assert len(service.enqueue_calls) == 1
