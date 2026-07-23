from collections.abc import Callable
from types import SimpleNamespace

import discord

from rosetta.utils import music_service

USER_ID = "123456789012345678"
CHANNEL_ID = "987654321098765432"
URL = "u"


def track(title: str, uri: str, *, thumbnail: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        title=title, uri=uri, author="artist", length=1234, thumbnail=thumbnail
    )


def playlist(tracks: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        tracks=tracks,
        name="playlist",
        uri="https://example.test/playlist",
        thumbnail="https://example.test/playlist.jpg",
    )


def permissions(*, connect: bool = True, speak: bool = True) -> SimpleNamespace:
    return SimpleNamespace(connect=connect, speak=speak)


def voice_state(channel: "FakeVoiceChannel") -> SimpleNamespace:
    return SimpleNamespace(channel=channel)


class FakeMember:
    def __init__(self, user_id: int, voice: SimpleNamespace | None) -> None:
        self.id = user_id
        self.voice = voice


class FakeFilters:
    def __init__(self) -> None:
        self.tags: list[str] = []

    def has_filter(self, *, filter_tag: str) -> bool:
        return filter_tag in self.tags


class FakeQueue:
    def __init__(self) -> None:
        self.items: list[SimpleNamespace] = []
        self.front = False
        self.shuffled = False
        self.loop_name = "unset"

    def add(self, tracks: list[SimpleNamespace]) -> None:
        self.items.extend(tracks)

    def add_front(self, tracks: list[SimpleNamespace]) -> None:
        self.front = True
        self.items = [*tracks, *self.items]

    def shuffle(self) -> None:
        self.shuffled = True

    def set_loop(self, mode: music_service.LoopMode) -> music_service.LoopMode:
        self.loop_name = mode.name
        return mode

    def get(self) -> SimpleNamespace | None:
        return None if not self.items else self.items.pop(0)


class FakeNode:
    def __init__(
        self,
        name: str,
        tracks: list[SimpleNamespace] | SimpleNamespace | BaseException | None,
    ) -> None:
        self._identifier = name
        self.tracks = tracks
        self.searches: list[str] = []
        self.players: dict[int, FakePlayer] = {}

    async def get_tracks(
        self, query: str, **kwargs: str
    ) -> list[SimpleNamespace] | SimpleNamespace | None:
        self.searches.append(query)
        if isinstance(self.tracks, BaseException):
            raise self.tracks
        return self.tracks

    def get_player(self, guild_id: int) -> "FakePlayer | None":
        return self.players.get(guild_id)


class FakePlayer:
    def __init__(
        self, node: FakeNode, channel: "FakeVoiceChannel", *, register: bool = True
    ) -> None:
        self.node = node
        self.channel = channel
        self.queue = FakeQueue()
        self.filters = FakeFilters()
        self.is_playing = False
        self.volume_calls: list[int] = []
        self.filter_payloads: list[str] = []
        self.played: list[SimpleNamespace | None] = []
        self.lookup_queries: list[str] = []
        if register:
            node.players[channel.guild.id] = self

    async def set_volume(self, volume: int) -> None:
        self.volume_calls.append(volume)

    async def add_filter(self, filter_value: music_service.lava_lyra.Filter) -> None:
        self.filter_payloads.append(filter_value.tag)
        self.filters.tags.append(filter_value.tag)

    async def get_tracks(
        self, query: str, **kwargs: str
    ) -> list[SimpleNamespace] | SimpleNamespace | None:
        self.lookup_queries.append(query)
        return await self.node.get_tracks(query, **kwargs)

    async def play(self, track_value: SimpleNamespace | None) -> SimpleNamespace | None:
        self.played.append(track_value)
        self.is_playing = True
        return track_value


class FakeGuild:
    def __init__(
        self,
        guild_id: int,
        *,
        fetch_error: discord.HTTPException | None = None,
    ) -> None:
        self.id = guild_id
        self.me = "bot-member"
        self.members: dict[int, FakeMember] = {}
        self.fetched_members: dict[int, FakeMember] = {}
        self.fetch_error = fetch_error
        self.get_member_calls: list[int] = []
        self.fetch_member_calls: list[int] = []

    def get_member(self, user_id: int) -> FakeMember | None:
        self.get_member_calls.append(user_id)
        return self.members.get(user_id)

    async def fetch_member(self, user_id: int) -> FakeMember:
        self.fetch_member_calls.append(user_id)
        if self.fetch_error is not None:
            raise self.fetch_error
        member = self.fetched_members.get(user_id)
        if member is None:
            raise discord.NotFound(
                SimpleNamespace(status=404, reason="Not Found"), "missing"
            )
        return member


class FakeVoiceChannel:
    def __init__(
        self, channel_id: int, guild: FakeGuild, channel_permissions: SimpleNamespace
    ) -> None:
        self.id = channel_id
        self.guild = guild
        self.permissions = channel_permissions
        self.connect_calls = 0
        self.next_player: FakePlayer | None = None

    def permissions_for(self, member: str) -> SimpleNamespace:
        return self.permissions

    async def connect(self, *, cls: Callable[..., FakePlayer]) -> FakePlayer:
        self.connect_calls += 1
        if self.next_player is None:
            self.next_player = cls("client", self)
        return self.next_player


class FakeBot:
    def __init__(
        self,
        channel: FakeVoiceChannel | str | None,
        fetch_error: discord.NotFound | None = None,
    ) -> None:
        self.channel = channel
        self.fetch_error = fetch_error
        self.get_calls = 0
        self.fetch_calls = 0

    def get_channel(self, channel_id: int) -> FakeVoiceChannel | str | None:
        self.get_calls += 1
        if isinstance(self.channel, str):
            return self.channel
        return (
            self.channel
            if self.channel is not None and self.channel.id == channel_id
            else None
        )

    async def fetch_channel(self, channel_id: int) -> FakeVoiceChannel | str | None:
        self.fetch_calls += 1
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.get_channel(channel_id)


class FakePool:
    def __init__(self, nodes: list[FakeNode]) -> None:
        self.nodes = {node._identifier: node for node in nodes}
        self.destroy_calls: list[int] = []

    def get_node(self, identifier: str | None = None) -> FakeNode:
        if identifier is None:
            return next(iter(self.nodes.values()))
        return self.nodes[identifier]

    async def destroy_guild_players(self, guild_id: int) -> None:
        self.destroy_calls.append(guild_id)


def make_target(
    tracks: list[SimpleNamespace] | SimpleNamespace | BaseException | None,
    *,
    channel_permissions: SimpleNamespace | None = None,
) -> tuple["music_service.MusicService", FakePool, FakeNode, FakeVoiceChannel]:
    guild = FakeGuild(10)
    channel = FakeVoiceChannel(
        int(CHANNEL_ID), guild, channel_permissions or permissions()
    )
    guild.members[int(USER_ID)] = FakeMember(int(USER_ID), voice_state(channel))
    node = FakeNode("MAIN", tracks)
    pool = FakePool([node])
    return music_service.MusicService(FakeBot(channel), pool), pool, node, channel
