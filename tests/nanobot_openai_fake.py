from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from tests.mcp_http_support import reserve_port


@dataclass(slots=True)
class FakeChatCompletions:
    requests: list[dict[str, Any]] = field(default_factory=list)

    async def handle(self, request: Request) -> JSONResponse | StreamingResponse:
        body = await request.json()
        self.requests.append(body)
        if body.get("stream") is True:
            return StreamingResponse(
                _stream_response(len(self.requests)),
                media_type="text/event-stream",
            )
        tools = body.get("tools") or []
        tool_names = [tool["function"]["name"] for tool in tools]
        if "mcp_rosetta_search" not in tool_names:
            return JSONResponse(
                _choice(
                    {
                        "role": "assistant",
                        "content": "Rosetta MCP search is unavailable.",
                    },
                    "stop",
                )
            )
        if len(self.requests) == 1:
            return JSONResponse(_choice(_tool_call_message(), "tool_calls"))
        return JSONResponse(_choice(_final_message(), "stop"))


def _tool_call_message() -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_rosetta_search",
                "type": "function",
                "function": {
                    "name": "mcp_rosetta_search",
                    "arguments": json.dumps({"keyword": "contract", "limit": 10}),
                },
            }
        ],
    }


def _final_message() -> dict[str, str]:
    return {
        "role": "assistant",
        "content": "Final track: Contract Song by Contract Artist.",
    }


def _choice(message: dict[str, Any], finish_reason: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "rosetta-test-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


async def _stream_response(request_number: int) -> AsyncIterator[str]:
    if request_number == 1:
        chunks = [
            _stream_chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_rosetta_search",
                            "type": "function",
                            "function": {
                                "name": "mcp_rosetta_search",
                                "arguments": json.dumps(
                                    {"keyword": "contract", "limit": 10}
                                ),
                            },
                        }
                    ]
                },
                None,
            ),
            _stream_chunk({}, "tool_calls"),
        ]
    else:
        chunks = [
            _stream_chunk(
                {"content": "Final track: Contract Song by Contract Artist."}, None
            ),
            _stream_chunk({}, "stop"),
        ]
    for chunk in chunks:
        yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"


def _stream_chunk(delta: dict[str, Any], finish_reason: str | None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "model": "rosetta-test-model",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@asynccontextmanager
async def fake_openai_server() -> AsyncIterator[str]:
    fake = FakeChatCompletions()
    app = Starlette(
        routes=[Route("/v1/chat/completions", fake.handle, methods=["POST"])]
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=reserve_port(),
            lifespan="off",
            log_level="warning",
            access_log=False,
        )
    )
    task = asyncio.create_task(server.serve())
    try:
        with anyio.fail_after(5):
            while not server.started:
                if task.done():
                    await task
                await anyio.sleep(0)
        yield f"http://127.0.0.1:{server.config.port}/v1"
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        except TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
