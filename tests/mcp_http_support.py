from __future__ import annotations

import json
import re
import socket
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from rosetta.mcp.runtime import MCPRuntime
from rosetta.models.music import (
    MusicFailure,
    PlayRequest,
    PlayResult,
    PlaySuccess,
    SearchResult,
    SearchSuccess,
    TrackSummary,
)
from rosetta.utils.config import McpSetting
from rosetta.utils.mcp_api_keys import McpApiKeyRepository

REDACTED_SECRET: Final = "<redacted>"
SNIPPET_PATTERN: Final = re.compile(
    r"```python\n(?P<code># mcp-client-snippet:start\n.*?# mcp-client-snippet:end)\n```",
    re.DOTALL,
)


@dataclass(slots=True)
class DeterministicHttpMusicService:
    search_calls: list[tuple[str, int]] = field(default_factory=list)
    play_calls: list[PlayRequest] = field(default_factory=list)
    backend_available: bool = True

    async def search(self, keyword: str, limit: int = 10) -> SearchResult:
        self.search_calls.append((keyword, limit))
        if not self.backend_available:
            return MusicFailure(
                code="music_backend_unavailable",
                message="No Lavalink node is available.",
            )
        return SearchSuccess(
            tracks=(
                TrackSummary(
                    title="Contract Song",
                    author="Contract Artist",
                    duration_ms=123456,
                    uri="https://youtube.example/watch?v=contract",
                    thumbnail=None,
                ),
            )
        )

    async def play(self, request: PlayRequest) -> PlayResult:
        self.play_calls.append(request)
        if not self.backend_available:
            return MusicFailure(
                code="music_backend_unavailable",
                message="No Lavalink node is available.",
            )
        if request.user_id != "111" or request.chat_channel_id != "222":
            return MusicFailure(
                code="user_not_in_channel",
                message="User is not connected to the requested voice channel.",
            )
        if request.url.endswith("conflict"):
            return MusicFailure(
                code="player_channel_conflict",
                message="A player is already active in another voice channel.",
            )
        return PlaySuccess(
            playback_status="started",
            title="Contract Song",
            uri=request.url,
            thumbnail=None,
            enqueued_count=1,
            node_name="TEST",
        )


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def mcp_settings(port: int) -> McpSetting:
    return McpSetting(
        ENABLED=True,
        HOST="127.0.0.1",
        PORT=port,
        PATH="/mcp",
        ALLOWED_HOSTS=["127.0.0.1", "localhost"],
        _env_file=None,
    )


async def create_mcp_runtime_with_key(
    service: DeterministicHttpMusicService,
    port: int,
) -> tuple[MCPRuntime, McpApiKeyRepository, str]:
    key_repository = McpApiKeyRepository(
        Path(tempfile.mkdtemp(prefix="rosetta-mcp-keys-")) / "settings.sqlite3"
    )
    created_key = await key_repository.create("integration-test")
    runtime = MCPRuntime(
        mcp_settings(port),
        service,
        api_key_validator=key_repository,
    )
    return runtime, key_repository, created_key.plaintext_key


async def call_tool(
    url: str, bearer_token: str, name: str, arguments: dict[str, str | int]
) -> dict[str, object]:
    import httpx2

    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=httpx2.Timeout(30.0, read=300.0),
        follow_redirects=True,
    ) as http_client:
        async with streamable_http_client(
            url,
            http_client=http_client,
        ) as (read_stream, write_stream, _session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                if result.structuredContent is not None:
                    return result.structuredContent
                return {
                    "is_error": result.isError,
                    "content": [
                        item.text for item in result.content if item.type == "text"
                    ],
                }


def read_readme_snippet() -> str:
    readme = Path("README.md").read_text(encoding="utf-8")
    match = SNIPPET_PATTERN.search(readme)
    if match is None:
        msg = "README MCP client snippet is missing"
        raise AssertionError(msg)
    return match.group("code")


def write_evidence(payload: dict[str, object]) -> None:
    path = Path(".omo/evidence/task-9-mcp-search-play.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
