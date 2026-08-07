from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Final

import anyio
import pytest

from rosetta.utils.mcp_api_keys import (
    ApiKeyNameAlreadyExists,
    ApiKeyNotFound,
    McpApiKeyRepository,
)
from rosetta.utils.settings_store import SCHEMA_VERSION

pytestmark = pytest.mark.anyio

KEY_PATTERN: Final = re.compile(r"^rst_mcp_[A-Za-z0-9_-]{43}$")
KEY_PREFIX_LENGTH: Final = 16


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def database_path(tmp_path: Path) -> Path:
    return tmp_path / ".data" / "mcp" / "api-keys.sqlite3"


async def user_version(path: Path) -> int:
    def read_version() -> int:
        with sqlite3.connect(path) as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
        assert row is not None
        return int(row[0])

    return await anyio.to_thread.run_sync(read_version)


async def table_names(path: Path) -> set[str]:
    def read_names() -> set[str]:
        with sqlite3.connect(path) as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        return {str(row[0]) for row in rows}

    return await anyio.to_thread.run_sync(read_names)


async def stored_key_hash(path: Path, name: str) -> str:
    def read_hash() -> str:
        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT key_hash FROM mcp_api_keys WHERE name = ?",
                (name,),
            ).fetchone()
        assert row is not None
        return str(row[0])

    return await anyio.to_thread.run_sync(read_hash)


async def test_create_migrates_database_and_generates_hash_only_key(
    tmp_path: Path,
) -> None:
    # Given: a repository path whose parent directory does not exist yet.
    path = database_path(tmp_path)
    repository = McpApiKeyRepository(path)

    # When: a named MCP API key is created.
    created = await repository.create("operator")

    # Then: migration creates the parent directory, schema version, table, and key metadata.
    assert path.parent.is_dir()
    assert await user_version(path) == SCHEMA_VERSION
    assert "mcp_api_keys" in await table_names(path)
    assert KEY_PATTERN.fullmatch(created.plaintext_key) is not None
    assert created.name == "operator"
    assert created.key_prefix == created.plaintext_key[:KEY_PREFIX_LENGTH]
    assert (
        created.fingerprint
        == hashlib.sha256(created.plaintext_key.encode("ascii")).hexdigest()[
            :KEY_PREFIX_LENGTH
        ]
    )
    assert created.plaintext_key.encode("ascii") not in path.read_bytes()
    assert (
        await stored_key_hash(path, "operator")
        == hashlib.sha256(created.plaintext_key.encode("ascii")).hexdigest()
    )


async def test_create_rejects_duplicate_names(tmp_path: Path) -> None:
    # Given: a repository with an existing named key.
    repository = McpApiKeyRepository(database_path(tmp_path))
    await repository.create("operator")

    # When / Then: creating the same name again fails with a typed duplicate error.
    with pytest.raises(ApiKeyNameAlreadyExists):
        await repository.create("operator")


async def test_list_returns_metadata_without_plaintext_or_hash(tmp_path: Path) -> None:
    # Given: two keys exist in the repository.
    repository = McpApiKeyRepository(database_path(tmp_path))
    first = await repository.create("operator")
    second = await repository.create("automation")

    # When: key metadata is listed.
    keys = await repository.list()

    # Then: callers receive stable metadata only, never plaintext keys or stored hashes.
    assert [(key.name, key.key_prefix, key.fingerprint) for key in keys] == [
        ("automation", second.key_prefix, second.fingerprint),
        ("operator", first.key_prefix, first.fingerprint),
    ]
    for key in keys:
        assert not hasattr(key, "plaintext_key")
        assert not hasattr(key, "key_hash")


async def test_delete_removes_key_and_unknown_name_is_typed_error(
    tmp_path: Path,
) -> None:
    # Given: a repository with one key.
    repository = McpApiKeyRepository(database_path(tmp_path))
    await repository.create("operator")

    # When: that key is deleted.
    await repository.delete("operator")

    # Then: it is absent from list results, and deleting an unknown name is typed.
    assert await repository.list() == []
    with pytest.raises(ApiKeyNotFound):
        await repository.delete("operator")


async def test_rotate_replaces_secret_material_and_preserves_name(
    tmp_path: Path,
) -> None:
    # Given: a repository with one key.
    path = database_path(tmp_path)
    repository = McpApiKeyRepository(path)
    original = await repository.create("operator")
    original_hash = await stored_key_hash(path, "operator")

    # When: the key is rotated.
    rotated = await repository.rotate("operator")

    # Then: the name is stable, while plaintext, prefix, fingerprint, and hash all change.
    assert rotated.name == "operator"
    assert rotated.plaintext_key != original.plaintext_key
    assert rotated.key_prefix != original.key_prefix
    assert rotated.fingerprint != original.fingerprint
    assert await stored_key_hash(path, "operator") != original_hash
    assert rotated.plaintext_key.encode("ascii") not in path.read_bytes()
    assert [key.name for key in await repository.list()] == ["operator"]


async def test_rotate_unknown_name_is_typed_error(tmp_path: Path) -> None:
    # Given: an empty repository.
    repository = McpApiKeyRepository(database_path(tmp_path))

    # When / Then: rotating an unknown key name fails with a typed not-found error.
    with pytest.raises(ApiKeyNotFound):
        await repository.rotate("missing")
