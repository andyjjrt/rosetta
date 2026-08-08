from typing import Annotated, Protocol

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field, StringConstraints

from rosetta.models.music import LoopModeName, PlayRequest, PlayResult, SearchResult


class McpMusicService(Protocol):
    async def search(self, keyword: str, limit: int = 10) -> SearchResult: ...

    async def play(self, request: PlayRequest) -> PlayResult: ...


def create_mcp_server(
    music: McpMusicService,
    *,
    streamable_http_path: str = "/mcp",
    transport_security: TransportSecuritySettings | None = None,
) -> FastMCP:
    # Rosetta tools are request/response only; stateless JSON avoids mcp 1.28.1
    # stateful SSE MemoryObjectReceiveStream leaks on normal streamable HTTP close.
    app = FastMCP(
        "rosetta-music",
        streamable_http_path=streamable_http_path,
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
    )

    @app.tool(name="search", structured_output=True)
    async def search(
        keyword: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)],
        limit: Annotated[int, Field(ge=1, le=25)] = 10,
    ) -> SearchResult:
        """Search YouTube for playable tracks.

        Args:
            keyword: Words to search for.
            limit: Maximum number of tracks to return, from 1 to 25.
        """
        return await music.search(keyword, limit)

    @app.tool(name="play", structured_output=True)
    async def play(
        user_id: Annotated[str, StringConstraints(pattern=r"^[0-9]+$")],
        chat_channel_id: Annotated[str, StringConstraints(pattern=r"^[0-9]+$")],
        url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)],
        loop: LoopModeName = LoopModeName.OFF,
        shuffle: bool = False,
        top: bool = False,
        node_name: str | None = None,
    ) -> PlayResult:
        """Play a URL in the specified user's current voice channel.

        Args:
            user_id: Decimal Discord ID of the user whose voice channel to use.
            chat_channel_id: Decimal Discord chat channel ID used to locate the guild.
            url: Playable YouTube URL to add to the queue.
            loop: Loop mode: Off, One, or Queue.
            shuffle: Whether to shuffle the added tracks.
            top: Whether to add the tracks to the front of the queue.
            node_name: Optional Lavalink node name to use for playback.
        """
        request = PlayRequest(
            user_id=user_id,
            chat_channel_id=chat_channel_id,
            url=url,
            loop=loop,
            shuffle=shuffle,
            top=top,
            node_name=node_name,
        )
        return await music.play(request)

    return app
