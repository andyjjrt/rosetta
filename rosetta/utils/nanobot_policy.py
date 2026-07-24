from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal, NewType

import anyio
from pydantic import AfterValidator, BaseModel, ConfigDict, StrictBool, ValidationError

GuildId = NewType("GuildId", str)
ChannelId = NewType("ChannelId", str)

_POLICY_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class GuildPolicyLoadError(Exception):
    path: Path
    reason: str

    def __str__(self) -> str:
        return f"failed to load Nanobot guild policy {self.path}: {self.reason}"


@dataclass(frozen=True, slots=True)
class GuildPolicy:
    enabled: bool
    channel_ids: frozenset[ChannelId]


def _parse_snowflake(value: str) -> str:
    if value.isascii() and value.isdigit():
        return value
    msg = "Discord snowflakes must be decimal strings"
    raise ValueError(msg)


type _SnowflakeString = Annotated[str, AfterValidator(_parse_snowflake)]


class _PolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class _StoredGuildPolicy(_PolicyModel):
    enabled: StrictBool
    channel_ids: tuple[_SnowflakeString, ...]


class _PolicyFile(_PolicyModel):
    version: Literal[1]
    guilds: dict[_SnowflakeString, _StoredGuildPolicy]


class GuildPolicyRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = anyio.Lock()

    async def get(self, guild_id: GuildId) -> GuildPolicy:
        async with self._lock:
            policy_file = self._load()
            return self._get(policy_file, guild_id)

    async def set_enabled(self, guild_id: GuildId, *, enabled: bool) -> None:
        async with self._lock:
            policy_file = self._load()
            self._assert_guild_id(guild_id)
            current = self._get(policy_file, guild_id)
            updated = GuildPolicy(enabled=enabled, channel_ids=current.channel_ids)
            self._write(self._with_policy(policy_file, guild_id, updated))

    async def add_channel(self, guild_id: GuildId, channel_id: ChannelId) -> None:
        async with self._lock:
            policy_file = self._load()
            self._assert_guild_id(guild_id)
            self._assert_channel_id(channel_id)
            current = self._get(policy_file, guild_id)
            updated = GuildPolicy(
                enabled=current.enabled,
                channel_ids=current.channel_ids | frozenset({channel_id}),
            )
            self._write(self._with_policy(policy_file, guild_id, updated))

    async def remove_channel(self, guild_id: GuildId, channel_id: ChannelId) -> None:
        async with self._lock:
            policy_file = self._load()
            self._assert_guild_id(guild_id)
            self._assert_channel_id(channel_id)
            current = self._get(policy_file, guild_id)
            updated = GuildPolicy(
                enabled=current.enabled,
                channel_ids=current.channel_ids - frozenset({channel_id}),
            )
            self._write(self._with_policy(policy_file, guild_id, updated))

    def _load(self) -> _PolicyFile:
        if not self._path.exists():
            return _PolicyFile(version=_POLICY_VERSION, guilds={})
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise GuildPolicyLoadError(self._path, str(error)) from error
        try:
            return _PolicyFile.model_validate(raw)
        except ValidationError as error:
            raise GuildPolicyLoadError(self._path, str(error)) from error

    def _write(self, policy_file: _PolicyFile) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(self._encode(policy_file))
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(str(temp_path), str(self._path))
        except OSError:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise

    def _encode(self, policy_file: _PolicyFile) -> str:
        guilds = {
            guild_id: {
                "enabled": stored.enabled,
                "channel_ids": sorted(stored.channel_ids, key=int),
            }
            for guild_id, stored in sorted(
                policy_file.guilds.items(), key=lambda item: int(item[0])
            )
        }
        return json.dumps(
            {"version": _POLICY_VERSION, "guilds": guilds},
            separators=(",", ":"),
        )

    def _get(self, policy_file: _PolicyFile, guild_id: GuildId) -> GuildPolicy:
        self._assert_guild_id(guild_id)
        stored = policy_file.guilds.get(guild_id)
        if stored is None:
            return GuildPolicy(enabled=False, channel_ids=frozenset())
        return GuildPolicy(
            enabled=stored.enabled,
            channel_ids=frozenset(
                ChannelId(channel_id) for channel_id in stored.channel_ids
            ),
        )

    def _with_policy(
        self, policy_file: _PolicyFile, guild_id: GuildId, policy: GuildPolicy
    ) -> _PolicyFile:
        guilds = dict(policy_file.guilds)
        guilds[guild_id] = _StoredGuildPolicy(
            enabled=policy.enabled,
            channel_ids=tuple(sorted(policy.channel_ids, key=int)),
        )
        return _PolicyFile(version=_POLICY_VERSION, guilds=guilds)

    def _assert_guild_id(self, guild_id: GuildId) -> None:
        self._parse_id(guild_id)

    def _assert_channel_id(self, channel_id: ChannelId) -> None:
        self._parse_id(channel_id)

    def _parse_id(self, value: str) -> None:
        try:
            _parse_snowflake(value)
        except ValueError as error:
            raise GuildPolicyLoadError(self._path, str(error)) from error
