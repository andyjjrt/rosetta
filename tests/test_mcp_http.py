from __future__ import annotations

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.mcp_http_support import (
    REDACTED_SECRET,
    DeterministicHttpMusicService,
    call_tool,
    create_mcp_runtime_with_key,
    read_readme_snippet,
    reserve_port,
    write_evidence,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_real_streamable_http_search_uri_play_contract() -> None:
    # Given: the real runtime/auth/server stack listens on a local TCP socket.
    service = DeterministicHttpMusicService()
    runtime, _key_repository, bearer_token = await create_mcp_runtime_with_key(
        service,
        reserve_port(),
    )
    await runtime.start()
    url = runtime.url + "/"
    try:
        # When: the official Streamable HTTP client initializes and calls search/play.
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
                    tools = await session.list_tools()
                    search = await session.call_tool(
                        "search", {"keyword": " contract "}
                    )
                    uri = search.structuredContent["result"]["tracks"][0]["uri"]
                    play = await session.call_tool(
                        "play",
                        {"user_id": "111", "chat_channel_id": "222", "url": uri},
                    )

        # Then: the exposed surface is exactly search/play and decimal-string play works.
        assert [tool.name for tool in tools.tools] == ["search", "play"]
        assert search.structuredContent == {
            "result": {
                "status": "success",
                "ok": True,
                "tracks": [
                    {
                        "title": "Contract Song",
                        "author": "Contract Artist",
                        "duration_ms": 123456,
                        "uri": "https://youtube.example/watch?v=contract",
                        "thumbnail": None,
                    }
                ],
            }
        }
        assert play.structuredContent == {
            "result": {
                "status": "success",
                "ok": True,
                "playback_status": "started",
                "title": "Contract Song",
                "uri": "https://youtube.example/watch?v=contract",
                "thumbnail": None,
                "enqueued_count": 1,
                "node_name": "TEST",
            }
        }
        assert service.search_calls == [("contract", 10)]
        assert service.play_calls[0].user_id == "111"
    finally:
        await runtime.stop()


async def test_http_failure_contracts_and_readme_snippet_are_executable() -> None:
    # Given: a local runtime and the README's documented client snippet.
    service = DeterministicHttpMusicService()
    runtime, _key_repository, bearer_token = await create_mcp_runtime_with_key(
        service,
        reserve_port(),
    )
    await runtime.start()
    url = runtime.url + "/"
    try:
        import httpx2

        namespace: dict[str, object] = {}
        exec(read_readme_snippet(), namespace)
        documented_flow = namespace["run_mcp_search_play"]

        # When: auth, malformed IDs, stale/backend and conflict paths are exercised.
        async with httpx2.AsyncClient(timeout=5, follow_redirects=True) as client:
            unauthorized = await client.post(url, headers={"Host": "127.0.0.1"})
        documented = await documented_flow(url, bearer_token, "contract", "111", "222")
        mismatch = await call_tool(
            url,
            bearer_token,
            "play",
            {
                "user_id": "111",
                "chat_channel_id": "333",
                "url": "https://youtube.example/watch?v=contract",
            },
        )
        conflict = await call_tool(
            url,
            bearer_token,
            "play",
            {
                "user_id": "111",
                "chat_channel_id": "222",
                "url": "https://youtube.example/watch?v=conflict",
            },
        )
        malformed = await call_tool(
            url,
            bearer_token,
            "play",
            {"user_id": "not-decimal", "chat_channel_id": "222", "url": "x"},
        )
        service.backend_available = False
        backend = await call_tool(url, bearer_token, "search", {"keyword": "contract"})

        # Then: every documented failure is either HTTP 401 or a structured MCP result.
        assert unauthorized.status_code == 401
        assert unauthorized.headers["www-authenticate"] == "Bearer"
        assert documented["tools"] == ["search", "play"]
        assert documented["play"]["result"]["ok"] is True
        assert mismatch["result"]["code"] == "user_not_in_channel"
        assert conflict["result"]["code"] == "player_channel_conflict"
        assert malformed["is_error"] is True
        assert "validation error" in malformed["content"][0]
        assert backend["result"]["code"] == "music_backend_unavailable"

        write_evidence(
            {
                "endpoint": runtime.url,
                "bearer": REDACTED_SECRET,
                "tools": documented["tools"],
                "search": documented["search"],
                "play": documented["play"],
                "unauthorized": {
                    "status": unauthorized.status_code,
                    "www_authenticate": unauthorized.headers["www-authenticate"],
                },
                "mismatched_user_channel": mismatch,
                "cross_channel_conflict": conflict,
                "malformed_id": malformed,
                "backend_unavailable": backend,
                "cleanup": "runtime.stop awaited in finally",
            }
        )
    finally:
        await runtime.stop()
