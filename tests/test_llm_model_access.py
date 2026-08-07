from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rosetta.utils.llm_model_access import (
    LlmModelAccessAlreadyGranted,
    LlmModelAccessNotFound,
    LlmModelAccessRepository,
)
from rosetta.utils.settings_store import SCHEMA_VERSION

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_repository_persists_llm_model_access_by_discord_user_id(
    tmp_path: Path,
) -> None:
    # Given: two repository instances share one settings database.
    database_path = tmp_path / "settings.sqlite3"
    writer = LlmModelAccessRepository(database_path)
    reader = LlmModelAccessRepository(database_path)

    # When: model-selection access is granted through one instance.
    created = await writer.add(123)

    # Then: the other instance observes the durable grant and metadata.
    assert created.user_id == 123
    assert await reader.is_allowed(123) is True
    assert await reader.list() == [created]


async def test_repository_rejects_duplicate_and_missing_llm_model_access(
    tmp_path: Path,
) -> None:
    # Given: one user already has model-selection access.
    repository = LlmModelAccessRepository(tmp_path / "settings.sqlite3")
    await repository.add(123)

    # When / Then: duplicate grants and unknown removals remain explicit.
    with pytest.raises(LlmModelAccessAlreadyGranted):
        await repository.add(123)
    with pytest.raises(LlmModelAccessNotFound):
        await repository.remove(456)


async def test_repository_removal_revokes_llm_model_access(tmp_path: Path) -> None:
    # Given: a user has model-selection access.
    repository = LlmModelAccessRepository(tmp_path / "settings.sqlite3")
    await repository.add(123)

    # When: the grant is removed.
    await repository.remove(123)

    # Then: authorization and listing both reflect the revocation.
    assert await repository.is_allowed(123) is False
    assert await repository.list() == []


async def test_llm_model_access_migration_advances_schema(tmp_path: Path) -> None:
    # Given: a fresh settings database.
    database_path = tmp_path / "settings.sqlite3"
    repository = LlmModelAccessRepository(database_path)

    # When: the repository first accesses its table.
    await repository.list()

    # Then: the versioned schema contains the LLM access table.
    with sqlite3.connect(database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("llm_model_access",),
        ).fetchone()
    assert version == SCHEMA_VERSION
    assert table == ("llm_model_access",)


async def test_llm_model_access_migrates_existing_version_one_database(
    tmp_path: Path,
) -> None:
    # Given: an existing settings database at the MCP-only schema version.
    database_path = tmp_path / "settings.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE mcp_api_keys (
                name TEXT PRIMARY KEY,
                key_hash TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL,
                rotated_at TEXT
            )
            """
        )
        connection.execute("PRAGMA user_version = 1")

    # When: the LLM model access repository opens the database.
    repository = LlmModelAccessRepository(database_path)
    await repository.add(123)

    # Then: the new table and version are installed without removing the old table.
    with sqlite3.connect(database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert version == SCHEMA_VERSION
    assert {"mcp_api_keys", "llm_model_access"} <= tables
    assert await repository.is_allowed(123) is True
