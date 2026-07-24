from __future__ import annotations

import json
import sys

import anyio
import pytest

from tests.nanobot_mcp_support import (
    run_nanobot_mcp_scenario,
    stream_nanobot_mcp_scenario,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_real_nanobot_sdk_searches_authenticated_rosetta_mcp() -> None:
    # Given: local fake OpenAI chat completions plus real authenticated Rosetta MCP.
    # When: the public Nanobot SDK runs against a deployment-shaped temp config.
    result = await run_nanobot_mcp_scenario(bearer_matches=True)

    # Then: Nanobot used the Rosetta search tool and returned deterministic track text.
    assert "mcp_rosetta_search" in result.tool_events
    assert result.search_calls == [("contract", 10)]
    assert "Contract Song" in result.final_content
    assert result.bad_token_zero_calls is None
    assert result.safe_failure_text is None
    assert result.closed_cleanly is True


async def test_real_nanobot_stream_searches_authenticated_rosetta_mcp() -> None:
    # Given: local fake OpenAI streaming plus real authenticated Rosetta MCP.
    # When: the public Nanobot stream API runs against deployment-shaped config.
    result = await stream_nanobot_mcp_scenario()

    # Then: streaming reports the Rosetta tool and returns deterministic track text.
    assert "mcp_rosetta_search" in result.tool_events
    assert result.search_calls == [("contract", 10)]
    assert "Contract Song" in result.final_content
    assert result.closed_cleanly is True


async def test_real_nanobot_sdk_rejects_wrong_mcp_bearer_without_secret_leak() -> None:
    # Given: Nanobot is configured with the wrong bearer token for Rosetta MCP.
    # When: the model attempts to call Rosetta search.
    result = await run_nanobot_mcp_scenario(bearer_matches=False)

    # Then: no Rosetta tool executes and the public/logged surface excludes tokens.
    assert result.search_calls == []
    assert result.bad_token_zero_calls is True
    assert result.safe_failure_text is not None
    assert "token" not in result.safe_failure_text.lower()
    assert "private-test-token" not in result.safe_failure_text
    assert result.closed_cleanly is True


async def test_real_nanobot_stream_rejects_wrong_mcp_bearer_without_secret_leak() -> (
    None
):
    # Given: public Nanobot stream is configured with a wrong Rosetta MCP bearer.
    # When: the stream scenario runs against the authenticated MCP boundary.
    result = await stream_nanobot_mcp_scenario(bearer_matches=False)

    # Then: no MCP tool is exposed/executed and the safe surface redacts tokens.
    assert result.tool_events == ()
    assert result.search_calls == []
    assert result.bad_token_zero_calls is True
    assert result.safe_failure_text is not None
    assert "token" not in result.safe_failure_text.lower()
    assert "private-test-token" not in result.safe_failure_text


async def _manual_main() -> None:
    bad = await run_nanobot_mcp_scenario(bearer_matches=False)
    stream = await stream_nanobot_mcp_scenario()
    sys.stdout.write(
        json.dumps(
            {
                "stream_tool_events": list(stream.tool_events),
                "stream_service_search_calls": stream.search_calls,
                "stream_final_content": stream.final_content,
                "bad_token_zero_calls": bad.bad_token_zero_calls,
                "bad_token_safe_failure": bad.safe_failure_text,
                "closed_cleanly": stream.closed_cleanly and bad.closed_cleanly,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    anyio.run(_manual_main)
