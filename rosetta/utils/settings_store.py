from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final

import anyio

SCHEMA_VERSION: Final = 2


class SettingsDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._migration_lock = anyio.Lock()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    async def migrate(self) -> None:
        async with self._migration_lock:
            await anyio.to_thread.run_sync(self._migrate_sync)

    def _migrate_sync(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_api_keys (
                    name TEXT PRIMARY KEY,
                    key_hash TEXT NOT NULL,
                    key_prefix TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    rotated_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_model_access (
                    user_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
