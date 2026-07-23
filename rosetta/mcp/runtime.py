from __future__ import annotations

import asyncio
import socket
from contextlib import ExitStack, asynccontextmanager, closing
from typing import Protocol

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import ASGIApp

from rosetta.mcp.auth import protect_mcp_app
from rosetta.mcp.server import McpMusicService, create_mcp_server
from rosetta.utils.config import McpSetting


class MCPRuntimeError(RuntimeError):
    pass


class MCPRuntimeAlreadyStartedError(MCPRuntimeError):
    pass


class MCPRuntimeStartupError(MCPRuntimeError):
    pass


class McpSessionManager(Protocol):
    def run(self): ...


class StreamableMCPServer(Protocol):
    @property
    def session_manager(self) -> McpSessionManager: ...

    def streamable_http_app(self) -> Starlette: ...


class McpServerFactory(Protocol):
    def __call__(
        self, music: McpMusicService, *, streamable_http_path: str
    ) -> StreamableMCPServer: ...


class MCPRuntime:
    def __init__(
        self,
        settings: McpSetting,
        music: McpMusicService,
        server_factory: McpServerFactory = create_mcp_server,
    ) -> None:
        self._settings = settings
        self._music = music
        self._server_factory = server_factory
        self._task: asyncio.Task[None] | None = None
        self._server: uvicorn.Server | None = None
        self._socket: socket.socket | None = None
        self._port: int = settings.PORT

    @property
    def url(self) -> str:
        return f"http://{self._settings.HOST}:{self._port}{self._settings.PATH}"

    async def start(self) -> None:
        if not self._settings.ENABLED:
            return
        if self._task is not None:
            raise MCPRuntimeAlreadyStartedError("MCP runtime is already started")

        self._settings.validate_startup()
        sock = self._bind_socket()
        with ExitStack() as socket_owner:
            socket_owner.enter_context(closing(sock))
            server = uvicorn.Server(self._config(self._asgi_app()))
            self._socket = sock
            socket_owner.pop_all()
        self._server = server
        self._task = asyncio.create_task(self._serve(server, self._socket))
        try:
            with anyio.fail_after(5):
                while not server.started:
                    if self._task.done():
                        await self._task
                    if server.should_exit:
                        raise MCPRuntimeStartupError(
                            "MCP runtime exited during startup"
                        )
                    await anyio.sleep(0)
        except asyncio.CancelledError:
            await self._cleanup_started_server()
            raise
        except MCPRuntimeStartupError:
            await self._cleanup_started_server()
            raise
        except TimeoutError as exc:
            await self._cleanup_started_server()
            raise MCPRuntimeStartupError(
                "MCP runtime did not start within 5 seconds"
            ) from exc

    async def _serve(self, server: uvicorn.Server, sock: socket.socket) -> None:
        try:
            await server.serve([sock])
        except SystemExit as exc:
            raise MCPRuntimeStartupError("MCP runtime exited during startup") from exc

    async def stop(self) -> None:
        task = self._task
        server = self._server
        sock = self._socket
        self._task = None
        self._server = None
        self._socket = None
        if task is None:
            return
        if server is not None:
            server.should_exit = True
        try:
            with anyio.fail_after(5, shield=True):
                await task
        except TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            if sock is not None:
                sock.close()

    async def _cleanup_started_server(self) -> None:
        with anyio.CancelScope(shield=True):
            await self.stop()

    def _bind_socket(self) -> socket.socket:
        family = socket.AF_INET6 if ":" in self._settings.HOST else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self._settings.HOST, self._settings.PORT))
        except OSError as exc:
            sock.close()
            message = f"MCP runtime could not bind {self._settings.HOST}:{self._settings.PORT}"
            raise MCPRuntimeStartupError(message) from exc
        self._port = sock.getsockname()[1]
        return sock

    def _asgi_app(self) -> ASGIApp:
        mcp = self._server_factory(self._music, streamable_http_path="/")
        streamable_app = mcp.streamable_http_app()

        @asynccontextmanager
        async def lifespan(_app: Starlette):
            async with mcp.session_manager.run():
                yield

        mounted = Starlette(
            routes=[Mount(self._settings.PATH, app=streamable_app)],
            lifespan=lifespan,
        )
        return protect_mcp_app(mounted, self._settings)

    def _config(self, app: ASGIApp) -> uvicorn.Config:
        return uvicorn.Config(
            app,
            host=self._settings.HOST,
            port=self._port,
            lifespan="on",
            log_level="info",
            access_log=False,
        )
