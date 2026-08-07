from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import anyio

from rosetta.utils.settings_store import SettingsDatabase

KEY_PREFIX: Final = "rst_mcp_"
SECRET_TOKEN_BYTES: Final = 32
KEY_VISIBLE_PREFIX_LENGTH: Final = 16


@dataclass(frozen=True, slots=True)
class McpApiKeyMetadata:
    name: str
    key_prefix: str
    fingerprint: str
    created_at: str
    rotated_at: str | None


@dataclass(frozen=True, slots=True)
class McpApiKeyCreateResult:
    name: str
    plaintext_key: str
    key_prefix: str
    fingerprint: str
    created_at: str
    rotated_at: str | None


@dataclass(frozen=True, slots=True)
class McpApiKeyRotateResult:
    name: str
    plaintext_key: str
    key_prefix: str
    fingerprint: str
    created_at: str
    rotated_at: str


class ApiKeyNameAlreadyExists(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"MCP API key name already exists: {name}")


class ApiKeyNotFound(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"MCP API key not found: {name}")


@dataclass(frozen=True, slots=True)
class _KeyMaterial:
    plaintext_key: str
    key_hash: str
    key_prefix: str
    fingerprint: str


class McpApiKeyRepository:
    def __init__(self, path: Path) -> None:
        self._database = SettingsDatabase(path)
        self._lock = anyio.Lock()

    async def create(self, name: str) -> McpApiKeyCreateResult:
        async with self._lock:
            await self._database.migrate()
            return await anyio.to_thread.run_sync(self._create_sync, name)

    async def list(self) -> list[McpApiKeyMetadata]:
        async with self._lock:
            await self._database.migrate()
            return await anyio.to_thread.run_sync(self._list_sync)

    async def delete(self, name: str) -> None:
        async with self._lock:
            await self._database.migrate()
            await anyio.to_thread.run_sync(self._delete_sync, name)

    async def rotate(self, name: str) -> McpApiKeyRotateResult:
        async with self._lock:
            await self._database.migrate()
            return await anyio.to_thread.run_sync(self._rotate_sync, name)

    async def is_valid_key(self, plaintext_key: str) -> bool:
        async with self._lock:
            await self._database.migrate()
            return await anyio.to_thread.run_sync(
                self._is_valid_key_sync, plaintext_key
            )

    def _create_sync(self, name: str) -> McpApiKeyCreateResult:
        material = _generate_key_material()
        with self._database.connect() as connection:
            now = self._current_timestamp(connection)
            try:
                connection.execute(
                    """
                    INSERT INTO mcp_api_keys (
                        name, key_hash, key_prefix, fingerprint, created_at, rotated_at
                    )
                    VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        name,
                        material.key_hash,
                        material.key_prefix,
                        material.fingerprint,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ApiKeyNameAlreadyExists(name) from error
        return McpApiKeyCreateResult(
            name=name,
            plaintext_key=material.plaintext_key,
            key_prefix=material.key_prefix,
            fingerprint=material.fingerprint,
            created_at=now,
            rotated_at=None,
        )

    def _list_sync(self) -> list[McpApiKeyMetadata]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT name, key_prefix, fingerprint, created_at, rotated_at
                FROM mcp_api_keys
                ORDER BY name ASC
                """
            ).fetchall()
        return [
            McpApiKeyMetadata(
                name=row["name"],
                key_prefix=row["key_prefix"],
                fingerprint=row["fingerprint"],
                created_at=row["created_at"],
                rotated_at=row["rotated_at"],
            )
            for row in rows
        ]

    def _delete_sync(self, name: str) -> None:
        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM mcp_api_keys WHERE name = ?",
                (name,),
            )
            if cursor.rowcount == 0:
                raise ApiKeyNotFound(name)

    def _rotate_sync(self, name: str) -> McpApiKeyRotateResult:
        material = _generate_key_material()
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT created_at FROM mcp_api_keys WHERE name = ?",
                (name,),
            ).fetchone()
            if row is None:
                raise ApiKeyNotFound(name)
            now = self._current_timestamp(connection)
            connection.execute(
                """
                UPDATE mcp_api_keys
                SET key_hash = ?, key_prefix = ?, fingerprint = ?, rotated_at = ?
                WHERE name = ?
                """,
                (
                    material.key_hash,
                    material.key_prefix,
                    material.fingerprint,
                    now,
                    name,
                ),
            )
        return McpApiKeyRotateResult(
            name=name,
            plaintext_key=material.plaintext_key,
            key_prefix=material.key_prefix,
            fingerprint=material.fingerprint,
            created_at=row["created_at"],
            rotated_at=now,
        )

    def _is_valid_key_sync(self, plaintext_key: str) -> bool:
        try:
            key_hash = _hash_key(plaintext_key)
        except UnicodeEncodeError:
            return False
        with self._database.connect() as connection:
            rows = connection.execute("SELECT key_hash FROM mcp_api_keys").fetchall()
        return any(secrets.compare_digest(row["key_hash"], key_hash) for row in rows)

    def _current_timestamp(self, connection: sqlite3.Connection) -> str:
        row = connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()
        return row[0]


def _generate_key_material() -> _KeyMaterial:
    plaintext_key = f"{KEY_PREFIX}{secrets.token_urlsafe(SECRET_TOKEN_BYTES)}"
    key_hash = _hash_key(plaintext_key)
    return _KeyMaterial(
        plaintext_key=plaintext_key,
        key_hash=key_hash,
        key_prefix=plaintext_key[:KEY_VISIBLE_PREFIX_LENGTH],
        fingerprint=key_hash[:KEY_VISIBLE_PREFIX_LENGTH],
    )


def _hash_key(plaintext_key: str) -> str:
    return hashlib.sha256(plaintext_key.encode("ascii")).hexdigest()
