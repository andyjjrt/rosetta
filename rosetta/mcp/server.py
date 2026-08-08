from typing import Annotated, Protocol

from mcp.server.fastmcp import FastMCP
from pydantic import Field, StringConstraints

from rosetta.models.music import LoopModeName, PlayRequest, PlayResult, SearchResult


class McpMusicService(Protocol):
    async def search(self, keyword: str, limit: int = 10) -> SearchResult: ...

    async def play(self, request: PlayRequest) -> PlayResult: ...


def create_mcp_server(
    music: McpMusicService, *, streamable_http_path: str = "/mcp"
) -> FastMCP:
    # Rosetta tools are request/response only; stateless JSON avoids mcp 1.28.1
    # stateful SSE MemoryObjectReceiveStream leaks on normal streamable HTTP close.
    app = FastMCP(
        "rosetta-music",
        streamable_http_path=streamable_http_path,
        stateless_http=True,
        json_response=True,
    )

    @app.tool(name="search", structured_output=True)
    async def search(
        keyword: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)],
        limit: Annotated[int, Field(ge=1, le=25)] = 10,
    ) -> SearchResult:
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
