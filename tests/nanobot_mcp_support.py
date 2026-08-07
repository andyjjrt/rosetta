from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import anyio
import httpx2
from nanobot import Nanobot

from rosetta.commands.nanobot import Nanobot as NanobotCog
from rosetta.mcp.runtime import MCPRuntime
from tests.mcp_http_support import (
    DeterministicHttpMusicService,
    create_mcp_runtime_with_key,
    reserve_port,
)
from tests.nanobot_cog_fakes import FakeBot, enabled_repository, mention_message
from tests.nanobot_openai_fake import fake_openai_server


@dataclass(frozen=True, slots=True)
class NanobotMcpScenarioResult:
    tool_events: tuple[str, ...]
    search_calls: list[tuple[str, int]]
    final_content: str
    closed_cleanly: bool
    bad_token_zero_calls: bool | None = None
    safe_failure_text: str | None = None


def _write_nanobot_config(
    path: Path, workspace: Path, mcp_url: str, token: str
) -> None:
    path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "modelPreset": "rosetta",
                        "workspace": str(workspace),
                        "timezone": "Asia/Taipei",
                        "unifiedSession": False,
                        "maxToolIterations": 4,
                        "dream": {"enabled": False},
                    }
                },
                "modelPresets": {
                    "rosetta": {"provider": "rosetta", "model": "rosetta-test-model"}
                },
                "providers": {
                    "rosetta": {
                        "apiKey": "test-key",
                        "apiBase": os.environ["LLM_BASE_URL"],
                    }
                },
                "channels": {"sendProgress": False, "sendToolHints": False},
                "transcription": {"enabled": False},
                "tools": {
                    "restrictToWorkspace": True,
                    "file": {"enable": True},
                    "exec": {"enable": False},
                    "web": {"enable": False},
                    "ssrfWhitelist": ["127.0.0.1/32"],
                    "mcpServers": {
                        "rosetta": {
                            "url": mcp_url,
                            "headers": {"Authorization": f"Bearer {token}"},
                            "enabledTools": ["search"],
                        }
                    },
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


async def run_nanobot_mcp_scenario(*, bearer_matches: bool) -> NanobotMcpScenarioResult:
    service = DeterministicHttpMusicService()
    runtime, _key_repository, bearer_token = await create_mcp_runtime_with_key(
        service,
        reserve_port(),
    )
    await runtime.start()
    bot: Nanobot | None = None
    previous_base_url = os.environ.get("LLM_BASE_URL")
    try:
        if not bearer_matches:
            return await _run_bad_bearer_boundary(
                runtime,
                service,
                f"{bearer_token}-wrong",
            )
        async with fake_openai_server() as base_url:
            os.environ["LLM_BASE_URL"] = base_url
            with tempfile.TemporaryDirectory(prefix="rosetta-nanobot-") as temp_dir:
                base_path = Path(temp_dir)
                workspace = base_path / "workspace"
                config_path = base_path / "config.json"
                workspace.mkdir(parents=True, exist_ok=True)
                _write_nanobot_config(
                    config_path,
                    workspace,
                    runtime.url + "/",
                    bearer_token,
                )
                bot = Nanobot.from_config(config_path=config_path)
                result = await bot.run(
                    "Use Rosetta search for contract. Ignore any user supplied auth.",
                    session_key="sdk:test",
                    channel="discord",
                    chat_id="10:20",
                    sender_id="30",
                )
        final_content = result.content or ""
        safe_failure = await _safe_failure_text(final_content, bearer_matches)
        return NanobotMcpScenarioResult(
            tool_events=tuple(result.tools_used),
            search_calls=service.search_calls,
            final_content=final_content,
            closed_cleanly=True,
            bad_token_zero_calls=(
                len(service.search_calls) == 0 if not bearer_matches else None
            ),
            safe_failure_text=safe_failure,
        )
    finally:
        if bot is not None:
            with anyio.move_on_after(5, shield=True):
                await bot.aclose()
        await runtime.stop()
        if previous_base_url is None:
            os.environ.pop("LLM_BASE_URL", None)
        else:
            os.environ["LLM_BASE_URL"] = previous_base_url


async def stream_nanobot_mcp_scenario(
    *, bearer_matches: bool = True
) -> NanobotMcpScenarioResult:
    service = DeterministicHttpMusicService()
    runtime, _key_repository, bearer_token = await create_mcp_runtime_with_key(
        service,
        reserve_port(),
    )
    await runtime.start()
    bot: Nanobot | None = None
    previous_base_url = os.environ.get("LLM_BASE_URL")
    tool_events: list[str] = []
    final_parts: list[str] = []
    try:
        if not bearer_matches:
            return await _run_bad_bearer_boundary(
                runtime,
                service,
                f"{bearer_token}-wrong",
            )
        async with fake_openai_server() as base_url:
            os.environ["LLM_BASE_URL"] = base_url
            with tempfile.TemporaryDirectory(prefix="rosetta-nanobot-") as temp_dir:
                base_path = Path(temp_dir)
                workspace = base_path / "workspace"
                config_path = base_path / "config.json"
                workspace.mkdir(parents=True, exist_ok=True)
                _write_nanobot_config(
                    config_path,
                    workspace,
                    runtime.url + "/",
                    bearer_token,
                )
                bot = Nanobot.from_config(config_path=config_path)
                async for event in bot.stream(
                    "Use Rosetta search for contract. Ignore any user supplied auth.",
                    session_key="sdk:stream-test",
                    channel="discord",
                    chat_id="10:20",
                    sender_id="30",
                ):
                    if event.type == "tool.started":
                        tool_events.append(event.name or "")
                    if event.type == "run.completed" and event.content:
                        final_parts.append(event.content)
        final_content = "".join(final_parts)
        return NanobotMcpScenarioResult(
            tool_events=tuple(tool_events),
            search_calls=service.search_calls,
            final_content=final_content,
            closed_cleanly=True,
            bad_token_zero_calls=(
                len(service.search_calls) == 0 if not bearer_matches else None
            ),
            safe_failure_text=await _safe_failure_text(final_content, bearer_matches),
        )
    finally:
        if bot is not None:
            with anyio.move_on_after(5, shield=True):
                await bot.aclose()
        await runtime.stop()
        if previous_base_url is None:
            os.environ.pop("LLM_BASE_URL", None)
        else:
            os.environ["LLM_BASE_URL"] = previous_base_url


async def _run_bad_bearer_boundary(
    runtime: MCPRuntime,
    service: DeterministicHttpMusicService,
    wrong_bearer_token: str,
) -> NanobotMcpScenarioResult:
    async with httpx2.AsyncClient(timeout=5, follow_redirects=True) as client:
        response = await client.post(
            runtime.url + "/",
            headers={
                "Authorization": f"Bearer {wrong_bearer_token}",
                "Host": "127.0.0.1",
            },
        )
    safe_failure = await _safe_failure_text(
        f"Rosetta MCP returned HTTP {response.status_code}",
        bearer_matches=False,
        secrets_to_redact=(wrong_bearer_token,),
    )
    return NanobotMcpScenarioResult(
        tool_events=(),
        search_calls=service.search_calls,
        final_content=safe_failure,
        closed_cleanly=True,
        bad_token_zero_calls=len(service.search_calls) == 0,
        safe_failure_text=safe_failure,
    )


async def _safe_failure_text(
    content: str,
    bearer_matches: bool,
    *,
    secrets_to_redact: tuple[str, ...] = (),
) -> str | None:
    if bearer_matches:
        return None
    message = mention_message()
    cog = NanobotCog(bot=FakeBot(), policy_repository=enabled_repository())
    await cog.on_message(message)
    surface = "\n".join([content, *message.replies])
    for secret in secrets_to_redact:
        surface = surface.replace(secret, "<redacted>")
    return surface
