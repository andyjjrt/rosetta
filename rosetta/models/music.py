from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints


def _parse_snowflake(value: str) -> str:
    if value.isascii() and value.isdigit():
        return value
    msg = "Discord snowflakes must be decimal strings"
    raise ValueError(msg)


type SnowflakeString = Annotated[str, AfterValidator(_parse_snowflake)]


@unique
class LoopModeName(StrEnum):
    OFF = "Off"
    ONE = "One"
    QUEUE = "Queue"


@unique
class MusicErrorCode(StrEnum):
    MUSIC_BACKEND_UNAVAILABLE = "music_backend_unavailable"
    CHANNEL_NOT_FOUND = "channel_not_found"
    NOT_VOICE_CHANNEL = "not_voice_channel"
    USER_NOT_IN_CHANNEL = "user_not_in_channel"
    BOT_PERMISSION_DENIED = "bot_permission_denied"
    PLAYER_CHANNEL_CONFLICT = "player_channel_conflict"
    NODE_NOT_FOUND = "node_not_found"
    NO_TRACKS_FOUND = "no_tracks_found"


class MusicModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class SearchRequest(MusicModel):
    keyword: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    limit: Annotated[int, Field(ge=1, le=25)] = 10


class TrackSummary(MusicModel):
    title: str
    author: str
    duration_ms: int
    uri: str
    thumbnail: str | None


class SearchSuccess(MusicModel):
    status: Literal["success"] = "success"
    ok: Literal[True] = True
    tracks: tuple[TrackSummary, ...]


class PlayRequest(MusicModel):
    user_id: SnowflakeString
    voice_channel_id: SnowflakeString
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    loop: LoopModeName = LoopModeName.OFF
    shuffle: bool = False
    top: bool = False
    node_name: str | None = None


class PlaySuccess(MusicModel):
    status: Literal["success"] = "success"
    ok: Literal[True] = True
    playback_status: Literal["started", "queued"]
    title: str
    uri: str
    thumbnail: str | None
    enqueued_count: int
    node_name: str


class MusicFailure(MusicModel):
    status: Literal["failure"] = "failure"
    ok: Literal[False] = False
    code: MusicErrorCode
    message: str


type SearchResult = Annotated[
    SearchSuccess | MusicFailure, Field(discriminator="status")
]
type PlayResult = Annotated[PlaySuccess | MusicFailure, Field(discriminator="status")]
