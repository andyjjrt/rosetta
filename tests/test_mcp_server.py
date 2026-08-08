from dataclasses import dataclass, field

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from rosetta.mcp.server import create_mcp_server
from rosetta.models.music import (
    MusicFailure,
    PlayRequest,
    PlayResult,
    PlaySuccess,
    SearchResult,
    SearchSuccess,
    TrackSummary,
)

pytestmark = pytest.mark.anyio


@dataclass(slots=True)
class DeterministicMusicService:
    search_result: SearchResult
    play_result: PlayResult
    search_calls: list[tuple[str, int]] = field(default_factory=list)
    play_calls: list[PlayRequest] = field(default_factory=list)

    async def search(self, keyword: str, limit: int = 10) -> SearchResult:
        self.search_calls.append((keyword, limit))
        return self.search_result

    async def play(self, request: PlayRequest) -> PlayResult:
        self.play_calls.append(request)
        return self.play_result


class ExplodingMusicService(DeterministicMusicService):
    async def search(self, keyword: str, limit: int = 10) -> SearchResult:
        self.search_calls.append((keyword, limit))
        raise RuntimeError("deterministic defect")


def track(uri: str = "https://example.test/watch?v=1") -> TrackSummary:
    return TrackSummary(
        title="Song",
        author="Artist",
        duration_ms=1234,
        uri=uri,
        thumbnail=None,
    )


def service(
    search_result: SearchResult | None = None,
    play_result: PlayResult | None = None,
) -> DeterministicMusicService:
    return DeterministicMusicService(
        search_result=search_result or SearchSuccess(tracks=(track(),)),
        play_result=play_result
        or PlaySuccess(
            playback_status="started",
            title="Song",
            uri="https://example.test/watch?v=1",
            thumbnail=None,
            enqueued_count=1,
            node_name="MAIN",
        ),
    )


async def test_list_tools_returns_exact_names_and_schemas() -> None:
    app = create_mcp_server(service())

    tools = {tool.name: tool for tool in await app.list_tools()}

    assert list(tools) == ["search", "play"]
    assert tools["search"].inputSchema == {
        "properties": {
            "keyword": {"minLength": 1, "title": "Keyword", "type": "string"},
            "limit": {
                "default": 10,
                "maximum": 25,
                "minimum": 1,
                "title": "Limit",
                "type": "integer",
            },
        },
        "required": ["keyword"],
        "title": "searchArguments",
        "type": "object",
    }
    assert tools["play"].inputSchema == {
        "$defs": {
            "LoopModeName": {
                "enum": ["Off", "One", "Queue"],
                "title": "LoopModeName",
                "type": "string",
            }
        },
        "properties": {
            "user_id": {
                "pattern": "^[0-9]+$",
                "title": "User Id",
                "type": "string",
            },
            "chat_channel_id": {
                "pattern": "^[0-9]+$",
                "title": "Chat Channel Id",
                "type": "string",
            },
            "url": {"minLength": 1, "title": "Url", "type": "string"},
            "loop": {"$ref": "#/$defs/LoopModeName", "default": "Off"},
            "shuffle": {"default": False, "title": "Shuffle", "type": "boolean"},
            "top": {"default": False, "title": "Top", "type": "boolean"},
            "node_name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Node Name",
            },
        },
        "required": ["user_id", "chat_channel_id", "url"],
        "title": "playArguments",
        "type": "object",
    }
    assert tools["search"].outputSchema["properties"] == {
        "result": {"$ref": "#/$defs/SearchResult"}
    }
    assert tools["play"].outputSchema["properties"] == {
        "result": {"$ref": "#/$defs/PlayResult"}
    }


async def test_search_uri_feeds_play_with_structured_success() -> None:
    music = service()
    app = create_mcp_server(music)

    search_content, search_payload = await app.call_tool(
        "search", {"keyword": " test "}
    )
    uri = search_payload["result"]["tracks"][0]["uri"]
    play_content, play_payload = await app.call_tool(
        "play",
        {"user_id": "30", "chat_channel_id": "20", "url": uri},
    )

    assert search_payload == {
        "result": {
            "status": "success",
            "ok": True,
            "tracks": [
                {
                    "title": "Song",
                    "author": "Artist",
                    "duration_ms": 1234,
                    "uri": "https://example.test/watch?v=1",
                    "thumbnail": None,
                }
            ],
        }
    }
    assert play_payload == {
        "result": {
            "status": "success",
            "ok": True,
            "playback_status": "started",
            "title": "Song",
            "uri": "https://example.test/watch?v=1",
            "thumbnail": None,
            "enqueued_count": 1,
            "node_name": "MAIN",
        }
    }
    assert search_content[0].type == "text"
    assert play_content[0].type == "text"
    assert music.search_calls == [("test", 10)]
    assert music.play_calls == [
        PlayRequest(user_id="30", chat_channel_id="20", url=uri)
    ]


async def test_structured_service_failures_stay_structured() -> None:
    music = service(
        search_result=SearchSuccess(tracks=()),
        play_result=MusicFailure(
            code="player_channel_conflict",
            message="Already playing elsewhere.",
        ),
    )
    app = create_mcp_server(music)

    search_payload = (await app.call_tool("search", {"keyword": "empty"}))[1]
    play_payload = (
        await app.call_tool(
            "play",
            {
                "user_id": "30",
                "chat_channel_id": "20",
                "url": "https://example.test/watch?v=1",
            },
        )
    )[1]

    assert search_payload == {"result": {"status": "success", "ok": True, "tracks": []}}
    assert play_payload == {
        "result": {
            "status": "failure",
            "ok": False,
            "code": "player_channel_conflict",
            "message": "Already playing elsewhere.",
        }
    }


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("search", {"keyword": "test", "limit": 26}),
        (
            "play",
            {
                "user_id": 30,
                "chat_channel_id": "20",
                "url": "https://example.test/watch?v=1",
            },
        ),
        (
            "play",
            {
                "user_id": "30",
                "chat_channel_id": "20",
                "url": "https://example.test/watch?v=1",
                "loop": "All",
            },
        ),
    ],
)
async def test_malformed_requests_are_tool_errors(
    tool_name: str, arguments: dict[str, str | int]
) -> None:
    app = create_mcp_server(service())

    with pytest.raises(ToolError):
        await app.call_tool(tool_name, arguments)


async def test_unexpected_exception_surfaces_as_tool_error() -> None:
    app = create_mcp_server(
        ExplodingMusicService(
            search_result=SearchSuccess(tracks=()),
            play_result=MusicFailure(code="music_backend_unavailable", message="down"),
        )
    )

    with pytest.raises(ToolError, match="deterministic defect"):
        await app.call_tool("search", {"keyword": "test"})
