from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import anyio
import pytest

from rosetta.utils.nanobot_policy import (
    ChannelId,
    GuildId,
    GuildPolicyLoadError,
    GuildPolicyRepository,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def policy_path(tmp_path: Path) -> Path:
    return tmp_path / ".data" / "nanobot" / "guild-policies.json"


def write_policy(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")


def sibling_temps(path: Path) -> list[Path]:
    return [entry for entry in path.parent.iterdir() if entry.name != path.name]


async def test_default_policy_when_file_and_guild_are_missing(tmp_path: Path) -> None:
    # Given: no policy file exists.
    path = policy_path(tmp_path)
    repository = GuildPolicyRepository(path)

    # When: an unknown guild is requested.
    policy = await repository.get(GuildId("10"))

    # Then: access fails closed and no file is created.
    assert policy.enabled is False
    assert policy.channel_ids == frozenset()
    assert path.exists() is False


async def test_enable_disable_and_channel_mutations_are_idempotent(
    tmp_path: Path,
) -> None:
    # Given: a new repository.
    path = policy_path(tmp_path)
    repository = GuildPolicyRepository(path)
    guild_id = GuildId("10")

    # When: the same mutations are applied repeatedly.
    await repository.set_enabled(guild_id, enabled=True)
    await repository.add_channel(guild_id, ChannelId("20"))
    await repository.add_channel(guild_id, ChannelId("20"))
    await repository.add_channel(guild_id, ChannelId("30"))
    await repository.remove_channel(guild_id, ChannelId("20"))
    await repository.remove_channel(guild_id, ChannelId("20"))
    await repository.set_enabled(guild_id, enabled=False)

    # Then: the policy contains each intended state change once.
    assert await repository.get(guild_id) == await GuildPolicyRepository(path).get(
        guild_id
    )
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "guilds": {"10": {"enabled": False, "channel_ids": ["30"]}},
    }


async def test_reload_persistence_and_deterministic_channel_ordering(
    tmp_path: Path,
) -> None:
    # Given: channels are inserted out of order.
    path = policy_path(tmp_path)
    repository = GuildPolicyRepository(path)
    guild_id = GuildId("10")

    await repository.set_enabled(guild_id, enabled=True)
    for channel_id in ("30", "20", "100"):
        await repository.add_channel(guild_id, ChannelId(channel_id))

    # When: a new repository instance reloads the same file.
    reloaded = await GuildPolicyRepository(path).get(guild_id)

    # Then: memory is immutable and disk JSON is deterministically ordered.
    assert reloaded.enabled is True
    assert reloaded.channel_ids == frozenset(
        {ChannelId("20"), ChannelId("30"), ChannelId("100")}
    )
    assert json.loads(path.read_text(encoding="utf-8"))["guilds"]["10"][
        "channel_ids"
    ] == ["20", "30", "100"]


async def test_concurrent_channel_updates_do_not_lose_data(tmp_path: Path) -> None:
    # Given: multiple callers will update the same guild at once.
    path = policy_path(tmp_path)
    repository = GuildPolicyRepository(path)
    guild_id = GuildId("10")
    expected = frozenset(ChannelId(str(channel_id)) for channel_id in range(20, 40))

    async def add(channel_id: ChannelId) -> None:
        await repository.add_channel(guild_id, channel_id)

    # When: the updates run concurrently through the repository.
    async with anyio.create_task_group() as task_group:
        for channel_id in expected:
            task_group.start_soon(add, channel_id)

    # Then: every update survives the read-modify-write cycle.
    assert (await repository.get(guild_id)).channel_ids == expected


@pytest.mark.parametrize(
    "payload",
    [
        "{not-json",
        json.dumps({"version": 2, "guilds": {}}),
        json.dumps({"version": 1, "guilds": []}),
        json.dumps(
            {"version": 1, "guilds": {"abc": {"enabled": True, "channel_ids": []}}}
        ),
        json.dumps(
            {"version": 1, "guilds": {"10": {"enabled": "yes", "channel_ids": []}}}
        ),
        json.dumps(
            {"version": 1, "guilds": {"10": {"enabled": True, "channel_ids": [20]}}}
        ),
        json.dumps(
            {"version": 1, "guilds": {"10": {"enabled": True, "channel_ids": ["x"]}}}
        ),
    ],
)
async def test_load_failures_are_typed_and_leave_source_unchanged(
    tmp_path: Path, payload: str
) -> None:
    # Given: the policy file contains malformed or invalid data.
    path = policy_path(tmp_path)
    write_policy(path, payload)
    original = path.read_bytes()
    repository = GuildPolicyRepository(path)

    # When / Then: loading fails closed with a typed error and source bytes stay put.
    with pytest.raises(GuildPolicyLoadError):
        await repository.get(GuildId("10"))
    assert path.read_bytes() == original


async def test_replace_failure_cleans_temporary_file_and_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: an existing valid source file and an atomic replace failure.
    from rosetta.utils import nanobot_policy

    path = policy_path(tmp_path)
    write_policy(path, json.dumps({"version": 1, "guilds": {}}))
    original = path.read_bytes()
    repository = GuildPolicyRepository(path)

    def fail_replace(source: str, destination: str) -> None:
        raise PermissionError(source, destination)

    monkeypatch.setattr(nanobot_policy.os, "replace", fail_replace)

    # When / Then: the expected write failure propagates and temp cleanup runs.
    with pytest.raises(PermissionError):
        await repository.add_channel(GuildId("10"), ChannelId("20"))
    assert path.read_bytes() == original
    assert sibling_temps(path) == []


@pytest.mark.parametrize("guild_id", ["", "abc", "-1", "1.5"])
async def test_runtime_guild_ids_must_be_decimal_strings(
    tmp_path: Path, guild_id: str
) -> None:
    # Given: callers provide an invalid guild ID string.
    repository = GuildPolicyRepository(policy_path(tmp_path))

    # When / Then: the repository rejects the invalid identifier without writing.
    with pytest.raises(GuildPolicyLoadError):
        await repository.set_enabled(GuildId(guild_id), enabled=True)


@pytest.mark.parametrize("channel_ids", [("",), ("abc",), ("-20", "1.5")])
async def test_runtime_channel_ids_must_be_decimal_strings(
    tmp_path: Path, channel_ids: Iterable[str]
) -> None:
    # Given: callers provide invalid channel ID strings.
    repository = GuildPolicyRepository(policy_path(tmp_path))

    # When / Then: the repository rejects the invalid identifier without writing.
    for channel_id in channel_ids:
        with pytest.raises(GuildPolicyLoadError):
            await repository.add_channel(GuildId("10"), ChannelId(channel_id))
