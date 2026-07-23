from types import SimpleNamespace

from rosetta.commands import music as music_module
from rosetta.commands.music import Music
from rosetta.models.music import (
    MusicFailure,
    PlayRequest,
    PlaySuccess,
    SearchSuccess,
    TrackSummary,
)
from rosetta.utils.views.Search import SearchView


class FakeLogger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def info(self, message: str) -> None:
        self.infos.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)


class FakeQueue:
    def __init__(self) -> None:
        self.items: list[SimpleNamespace] = []
        self.loop: music_module.LoopMode | None = None
        self.front = False
        self.shuffled = False

    def add(self, tracks: list[SimpleNamespace]) -> None:
        self.items.extend(tracks)

    def add_front(self, tracks: list[SimpleNamespace]) -> None:
        self.front = True
        self.items = [*tracks, *self.items]

    def shuffle(self) -> None:
        self.shuffled = True

    def set_loop(self, mode: music_module.LoopMode) -> music_module.LoopMode:
        self.loop = mode
        return mode

    def get(self) -> SimpleNamespace | None:
        return None if not self.items else self.items.pop(0)


class FakeFilters:
    def __init__(self) -> None:
        self.tags: list[str] = []

    def has_filter(self, *, filter_tag: str) -> bool:
        return filter_tag in self.tags


class FakePlayer:
    def __init__(self, node: SimpleNamespace, tracks: list[SimpleNamespace]) -> None:
        self.node = node
        self.channel = SimpleNamespace(id=20)
        self.queue = FakeQueue()
        self.filters = FakeFilters()
        self.is_playing = False
        self.tracks = tracks
        self.volume_calls: list[int] = []
        self.filter_tags: list[str] = []
        self.lookup_queries: list[str] = []
        self.played: list[SimpleNamespace | None] = []

    async def set_volume(self, volume: int) -> None:
        self.volume_calls.append(volume)

    async def add_filter(self, filter_value: music_module.lava_lyra.Filter) -> None:
        self.filter_tags.append(filter_value.tag)
        self.filters.tags.append(filter_value.tag)

    async def get_tracks(
        self, query: str, search_type: music_module.lava_lyra.URLRegex
    ) -> list[SimpleNamespace]:
        self.lookup_queries.append(query)
        return self.tracks

    async def play(self, track_value: SimpleNamespace | None) -> SimpleNamespace | None:
        self.played.append(track_value)
        self.is_playing = True
        return track_value


class FakeVoiceChannel:
    def __init__(self, guild: "FakeGuild", player: FakePlayer) -> None:
        self.id = 20
        self.guild = guild
        self.connected_player = player
        self.connect_calls = 0

    async def connect(self, *, cls: type[music_module.CustomPlayer]) -> FakePlayer:
        self.connect_calls += 1
        return self.connected_player


class FakeVoiceState:
    def __init__(self, channel: FakeVoiceChannel) -> None:
        self.channel = channel


class FakeGuild:
    def __init__(self) -> None:
        self.id = 10
        self.name = "guild"
        self.voice_client: FakePlayer | None = None


class FakeUser:
    def __init__(self, voice: FakeVoiceState | None) -> None:
        self.id = 30
        self.name = "tester"
        self.avatar = "avatar-url"
        self.voice = voice

    def __str__(self) -> str:
        return self.name


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = False
        self.sent_embeds: list[music_module.discord.Embed] = []
        self.edited_views: list[SearchView] = []

    async def defer(self, *, ephemeral: bool = False) -> None:
        self.deferred = True

    async def send_message(self, *, embed: music_module.discord.Embed) -> None:
        self.sent_embeds.append(embed)

    async def edit_message(self, *, view: SearchView) -> None:
        self.edited_views.append(view)


class FakeMessage:
    def __init__(self) -> None:
        self.edited_embeds: list[music_module.discord.Embed] = []

    async def edit(self, *, embed: music_module.discord.Embed) -> None:
        self.edited_embeds.append(embed)


class FakeFollowup:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message
        self.sent_embeds: list[music_module.discord.Embed] = []
        self.sent_views: list[SearchView] = []
        self.wait_values: list[bool] = []

    async def send(
        self,
        *,
        embed: music_module.discord.Embed | None = None,
        view: SearchView | None = None,
        wait: bool = False,
    ) -> FakeMessage:
        if embed is not None:
            self.sent_embeds.append(embed)
        if view is not None:
            self.sent_views.append(view)
        self.wait_values.append(wait)
        return self.message


class FakeInteraction:
    def __init__(self, user: FakeUser, guild: FakeGuild | None = None) -> None:
        self.user = user
        self.guild = guild
        self.guild_id = guild.id if guild is not None else None
        self.channel = SimpleNamespace(id=40)
        self.command = None
        self.response = FakeResponse()
        self.message = FakeMessage()
        self.followup = FakeFollowup(self.message)
        self.extras = {"logger": FakeLogger()}
        self.data = {
            "values": ["https://selected.example/track"],
            "custom_id": "song_select",
        }


class FakePool:
    def __init__(self, tracks: list[SimpleNamespace]) -> None:
        self.node = SimpleNamespace(_identifier="MAIN", get_tracks=self.get_tracks)
        self.nodes = {"MAIN": self.node}
        self.tracks = tracks
        self.destroy_calls: list[int] = []
        self.searches: list[str] = []

    def get_node(self) -> SimpleNamespace:
        return self.node

    async def get_tracks(self, keyword: str) -> list[SimpleNamespace]:
        self.searches.append(keyword)
        return self.tracks

    async def destroy_guild_players(self, guild_id: int) -> None:
        self.destroy_calls.append(guild_id)


class FakeService:
    def __init__(self, search_result: SearchSuccess | MusicFailure) -> None:
        self.search_result = search_result
        self.enqueue_result: PlaySuccess | MusicFailure = PlaySuccess(
            playback_status="started",
            title="Service Song",
            uri="https://service.example/song",
            thumbnail="https://service.example/thumb.jpg",
            enqueued_count=1,
            node_name="MAIN",
        )
        self.search_calls: list[tuple[str, int]] = []
        self.enqueue_calls: list[tuple[FakePlayer, PlayRequest]] = []

    async def search(
        self, keyword: str, limit: int = 10
    ) -> SearchSuccess | MusicFailure:
        self.search_calls.append((keyword, limit))
        return self.search_result

    async def enqueue(
        self, player: FakePlayer, request: PlayRequest
    ) -> PlaySuccess | MusicFailure:
        self.enqueue_calls.append((player, request))
        return self.enqueue_result


def music_cog(pool: FakePool) -> Music:
    music = Music.__new__(Music)
    music.bot = SimpleNamespace(user=SimpleNamespace(name="bot", avatar="bot-avatar"))
    music.pool = pool
    music.service = music_module.MusicService(music.bot, pool)
    return music


def summary(title: str, uri: str = "https://summary.example/song") -> TrackSummary:
    return TrackSummary(
        title=title,
        author="summary artist",
        duration_ms=125_000,
        uri=uri,
        thumbnail="https://summary.example/thumb.jpg",
    )


def track(title: str, uri: str = "https://track.example/song") -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        uri=uri,
        author="artist",
        length=125_000,
        thumbnail="https://track.example/thumb.jpg",
    )
