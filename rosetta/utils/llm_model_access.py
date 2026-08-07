from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import anyio

from rosetta.utils.settings_store import SettingsDatabase


@dataclass(frozen=True, slots=True)
class LlmModelAccessEntry:
    user_id: int
    created_at: str


class LlmModelAccessAlreadyGranted(Exception):
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(f"LLM model access already granted: {user_id}")


class LlmModelAccessNotFound(Exception):
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(f"LLM model access not found: {user_id}")


class LlmModelAccessRepository:
    def __init__(self, path: Path) -> None:
        self._database = SettingsDatabase(path)
        self._lock = anyio.Lock()

    async def add(self, user_id: int) -> LlmModelAccessEntry:
        async with self._lock:
            await self._database.migrate()
            return await anyio.to_thread.run_sync(self._add_sync, user_id)

    async def remove(self, user_id: int) -> None:
        async with self._lock:
            await self._database.migrate()
            await anyio.to_thread.run_sync(self._remove_sync, user_id)

    async def list(self) -> list[LlmModelAccessEntry]:
        async with self._lock:
            await self._database.migrate()
            return await anyio.to_thread.run_sync(self._list_sync)

    async def is_allowed(self, user_id: int) -> bool:
        async with self._lock:
            await self._database.migrate()
            return await anyio.to_thread.run_sync(self._is_allowed_sync, user_id)

    def _add_sync(self, user_id: int) -> LlmModelAccessEntry:
        with self._database.connect() as connection:
            created_at = connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
            try:
                connection.execute(
                    "INSERT INTO llm_model_access (user_id, created_at) VALUES (?, ?)",
                    (str(user_id), created_at),
                )
            except sqlite3.IntegrityError as error:
                raise LlmModelAccessAlreadyGranted(user_id) from error
        return LlmModelAccessEntry(user_id=user_id, created_at=created_at)

    def _remove_sync(self, user_id: int) -> None:
        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM llm_model_access WHERE user_id = ?",
                (str(user_id),),
            )
            if cursor.rowcount == 0:
                raise LlmModelAccessNotFound(user_id)

    def _list_sync(self) -> list[LlmModelAccessEntry]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT user_id, created_at FROM llm_model_access ORDER BY user_id ASC"
            ).fetchall()
        return [
            LlmModelAccessEntry(
                user_id=int(row["user_id"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _is_allowed_sync(self, user_id: int) -> bool:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM llm_model_access WHERE user_id = ?",
                (str(user_id),),
            ).fetchone()
        return row is not None


__all__ = (
    "LlmModelAccessAlreadyGranted",
    "LlmModelAccessEntry",
    "LlmModelAccessNotFound",
    "LlmModelAccessRepository",
)
