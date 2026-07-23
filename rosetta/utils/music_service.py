from dataclasses import dataclass
from functools import partial
from typing import Protocol, assert_never

import discord
import lava_lyra
from discord.ext import commands
from lava_lyra.exceptions import NodeNotAvailable, NodeRestException, NoNodesAvailable

from rosetta.models.music import (
    LoopModeName,
    MusicErrorCode,
    MusicFailure,
    PlayRequest,
    PlayResult,
    PlaySuccess,
    SearchRequest,
    SearchResult,
    SearchSuccess,
    TrackSummary,
)
from rosetta.utils.nodepool import HybridNodePool
from rosetta.utils.player import CustomPlayer
from rosetta.utils.queue import LoopMode


class TrackLike(Protocol):
    title: str
    author: str
    length: int
    uri: str
    thumbnail: str | None


class PlaylistLike(Protocol):
    tracks: list[TrackLike]
    name: str
    uri: str
    thumbnail: str | None


class MusicService:
    def __init__(self, bot: commands.Bot, pool: HybridNodePool) -> None:
        self._bot = bot
        self._pool = pool

    def parse_search(self, *, keyword: str, limit: int = 10) -> SearchRequest:
        return SearchRequest(keyword=keyword, limit=limit)

    async def search(self, keyword: str, limit: int = 10) -> SearchResult:
        request = self.parse_search(keyword=keyword, limit=limit)
        node = self._get_node(None)
        if node is None:
            return self._failure(
                MusicErrorCode.MUSIC_BACKEND_UNAVAILABLE,
                "No Lavalink node is available.",
            )
        try:
            results = await node.get_tracks(request.keyword)
        except (NoNodesAvailable, NodeNotAvailable, NodeRestException):
            return self._backend_unavailable()
        tracks = self._flatten_tracks(results)[: request.limit]
        return SearchSuccess(tracks=tuple(self._summary(track) for track in tracks))

    async def play(self, request: PlayRequest) -> PlayResult:
        selected_node = self._get_node(request.node_name)
        if selected_node is None:
            if request.node_name is None:
                return self._backend_unavailable()
            return self._node_not_found()

        target = await self._resolve_target(request)
        if isinstance(target, MusicFailure):
            return target

        player = self._guild_player(target.guild.id)
        if player is not None and player.channel.id != target.channel.id:
            return self._failure(
                MusicErrorCode.PLAYER_CHANNEL_CONFLICT,
                "A player is already active in another voice channel.",
            )
        if player is None:
            await self._pool.destroy_guild_players(target.guild.id)
            player_cls = (
                partial(CustomPlayer, node_identifier=request.node_name)
                if request.node_name
                else CustomPlayer
            )
            player = await target.channel.connect(cls=player_cls)

        return await self.enqueue(player, request)

    async def enqueue(self, player: CustomPlayer, request: PlayRequest) -> PlayResult:
        try:
            results = await player.get_tracks(
                query=request.url, search_type=lava_lyra.URLRegex.YOUTUBE_URL
            )
        except (NoNodesAvailable, NodeNotAvailable, NodeRestException):
            return self._backend_unavailable()
        tracks = self._flatten_tracks(results)
        if not tracks:
            return self._failure(
                MusicErrorCode.NO_TRACKS_FOUND, "No tracks were found."
            )

        await player.set_volume(20)
        normalization = lava_lyra.Filter(tag="play-normalization")
        normalization.payload = {
            "pluginFilters": {"normalization": {"maxAmplitude": 0.05, "adaptive": True}}
        }
        if not player.filters.has_filter(filter_tag=normalization.tag):
            await player.add_filter(normalization)

        if self._is_playlist(results):
            title = results.name
            uri = results.uri
            thumbnail = results.thumbnail
        else:
            first = tracks[0]
            title = first.title
            uri = first.uri
            thumbnail = first.thumbnail

        if request.top:
            player.queue.add_front(tracks)
        else:
            player.queue.add(tracks)
        if request.shuffle:
            player.queue.shuffle()
        player.queue.set_loop(self._loop_mode(request.loop))

        playback_status = "queued"
        if not player.is_playing:
            await player.play(player.queue.get())
            playback_status = "started"

        return PlaySuccess(
            playback_status=playback_status,
            title=title,
            uri=uri,
            thumbnail=thumbnail,
            enqueued_count=len(tracks),
            node_name=player.node._identifier,
        )

    async def _resolve_target(
        self, request: PlayRequest
    ) -> "ResolvedTarget | MusicFailure":
        user_id = int(request.user_id)
        channel_id = int(request.voice_channel_id)
        channel = self._bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._bot.fetch_channel(channel_id)
            except discord.NotFound:
                return self._channel_not_found()
        if channel is None:
            return self._channel_not_found()
        if not isinstance(channel, discord.VoiceChannel):
            return self._failure(
                MusicErrorCode.NOT_VOICE_CHANNEL,
                "Target channel is not a voice channel.",
            )

        guild = channel.guild
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                return self._failure(
                    MusicErrorCode.USER_NOT_IN_CHANNEL,
                    "User is not in the target channel.",
                )
        voice_state = member.voice
        member_channel = voice_state.channel if voice_state is not None else None
        if member_channel is None or member_channel.id != channel.id:
            return self._failure(
                MusicErrorCode.USER_NOT_IN_CHANNEL, "User is not in the target channel."
            )
        permissions = channel.permissions_for(guild.me)
        if not permissions.connect or not permissions.speak:
            return self._failure(
                MusicErrorCode.BOT_PERMISSION_DENIED,
                "Bot lacks connect or speak permission.",
            )
        return ResolvedTarget(guild=guild, channel=channel)

    def _get_node(self, node_name: str | None) -> lava_lyra.Node | None:
        if not self._pool.nodes:
            return None
        if node_name is None:
            return self._pool.get_node()
        try:
            return self._pool.get_node(identifier=node_name)
        except KeyError:
            return None

    def _guild_player(self, guild_id: int) -> CustomPlayer | None:
        for node in self._pool.nodes.values():
            player = node.get_player(guild_id)
            if player is not None:
                return player
        return None

    def _flatten_tracks(
        self, results: list[TrackLike] | PlaylistLike | None
    ) -> list[TrackLike]:
        if results is None:
            return []
        if self._is_playlist(results):
            return results.tracks
        return results

    def _is_playlist(self, results: list[TrackLike] | PlaylistLike | None) -> bool:
        return hasattr(results, "tracks")

    def _loop_mode(self, loop: LoopModeName) -> LoopMode:
        match loop:
            case LoopModeName.OFF:
                return LoopMode.NONE
            case LoopModeName.ONE:
                return LoopMode.ONE
            case LoopModeName.QUEUE:
                return LoopMode.QUEUE
            case _ as unreachable:
                assert_never(unreachable)

    def _summary(self, track: TrackLike) -> TrackSummary:
        return TrackSummary(
            title=track.title,
            author=track.author,
            duration_ms=track.length,
            uri=track.uri,
            thumbnail=track.thumbnail,
        )

    def _failure(self, code: MusicErrorCode, message: str) -> MusicFailure:
        return MusicFailure(code=code, message=message)

    def _backend_unavailable(self) -> MusicFailure:
        return self._failure(
            MusicErrorCode.MUSIC_BACKEND_UNAVAILABLE,
            "Music backend is unavailable.",
        )

    def _channel_not_found(self) -> MusicFailure:
        return self._failure(
            MusicErrorCode.CHANNEL_NOT_FOUND,
            "Voice channel was not found.",
        )

    def _node_not_found(self) -> MusicFailure:
        return self._failure(
            MusicErrorCode.NODE_NOT_FOUND,
            "Requested Lavalink node was not found.",
        )


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    guild: discord.Guild
    channel: discord.VoiceChannel
