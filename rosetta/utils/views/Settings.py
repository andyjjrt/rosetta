from __future__ import annotations

from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from typing import Final, Generic, Protocol, TypeVar

import discord

RowValueT = TypeVar("RowValueT")

DENIAL_MESSAGE: Final = "Only the original settings owner can use this view."


class OwnerCheck(Protocol):
    def __call__(self, interaction: discord.Interaction) -> Awaitable[bool]: ...


@dataclass(frozen=True, slots=True)
class SettingsListConfigError(ValueError):
    field_name: str
    reason: str

    def __str__(self) -> str:
        return f"{self.field_name}: {self.reason}"


@dataclass(frozen=True, slots=True)
class SettingsListRow(Generic[RowValueT]):
    title: str
    detail: str
    value: RowValueT


@dataclass(frozen=True, slots=True)
class SettingsListConfig(Generic[RowValueT]):
    title: str
    rows: Sequence[SettingsListRow[RowValueT]]
    empty_message: str
    owner_check: OwnerCheck
    custom_id_prefix: str
    accent: int | discord.Colour | None = None
    page_size: int = 5
    allowed_mentions: discord.AllowedMentions = field(
        default_factory=discord.AllowedMentions.none
    )

    def __post_init__(self) -> None:
        if self.custom_id_prefix.strip() == "":
            raise SettingsListConfigError("custom_id_prefix", "must not be blank")
        if self.page_size < 1:
            raise SettingsListConfigError("page_size", "must be at least 1")


class SettingsListView(discord.ui.LayoutView, Generic[RowValueT]):
    def __init__(self, config: SettingsListConfig[RowValueT]) -> None:
        super().__init__(timeout=300)
        self._config = config
        self._rows = tuple(config.rows)
        self._page = 1
        self.container = self._build_container()
        self.add_item(self.container)

    def replace_rows(self, rows: Sequence[SettingsListRow[RowValueT]]) -> None:
        self._rows = tuple(rows)
        self._page = min(self._page, self._total_pages())
        self._refresh_container()

    def visible_text(self) -> tuple[str, ...]:
        return tuple(self._page_text())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self._ensure_owner(interaction)

    async def go_previous(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_owner(interaction):
            return
        self._page = max(1, self._page - 1)
        await self._edit(interaction)

    async def go_next(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_owner(interaction):
            return
        self._page = min(self._total_pages(), self._page + 1)
        await self._edit(interaction)

    async def _ensure_owner(self, interaction: discord.Interaction) -> bool:
        if await self._config.owner_check(interaction):
            return True
        await interaction.response.send_message(DENIAL_MESSAGE, ephemeral=True)
        return False

    async def _edit(self, interaction: discord.Interaction) -> None:
        self._refresh_container()
        await interaction.response.edit_message(
            view=self,
            allowed_mentions=self._config.allowed_mentions,
        )

    def _refresh_container(self) -> None:
        self.clear_items()
        self.container = self._build_container()
        self.add_item(self.container)

    def _build_container(self) -> discord.ui.Container[SettingsListView[RowValueT]]:
        container = discord.ui.Container(
            discord.ui.TextDisplay(self._header_text()),
            discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small),
            accent_color=self._config.accent,
        )
        page_rows = self._page_rows()
        if page_rows:
            for index, row in page_rows:
                container.add_item(discord.ui.TextDisplay(self._row_text(index, row)))
                if index < self._page_end_index():
                    container.add_item(
                        discord.ui.Separator(
                            spacing=discord.enums.SeparatorSpacing.small
                        )
                    )
        else:
            container.add_item(discord.ui.TextDisplay(self._config.empty_message))

        container.add_item(
            discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small)
        )
        container.add_item(discord.ui.TextDisplay(self._footer_text()))
        controls = self._pagination_controls()
        if controls is not None:
            container.add_item(controls)
        return container

    def _pagination_controls(
        self,
    ) -> discord.ui.ActionRow[SettingsListView[RowValueT]] | None:
        if self._total_pages() <= 1:
            return None
        previous_button = discord.ui.Button(
            label="Previous",
            custom_id=f"{self._config.custom_id_prefix}:previous",
            disabled=self._page <= 1,
        )
        previous_button.callback = self.go_previous
        next_button = discord.ui.Button(
            label="Next",
            custom_id=f"{self._config.custom_id_prefix}:next",
            disabled=self._page >= self._total_pages(),
        )
        next_button.callback = self.go_next
        return discord.ui.ActionRow(previous_button, next_button)

    def _page_text(self) -> tuple[str, ...]:
        rows = tuple(self._row_text(index, row) for index, row in self._page_rows())
        if rows:
            return (self._header_text(), *rows, self._footer_text())
        return (self._header_text(), self._config.empty_message, self._footer_text())

    def _page_rows(self) -> tuple[tuple[int, SettingsListRow[RowValueT]], ...]:
        start = (self._page - 1) * self._config.page_size
        end = min(start + self._config.page_size, len(self._rows))
        return tuple(enumerate(self._rows[start:end], start=start + 1))

    def _page_end_index(self) -> int:
        return min(self._page * self._config.page_size, len(self._rows))

    def _total_pages(self) -> int:
        return max(
            1, (len(self._rows) + self._config.page_size - 1) // self._config.page_size
        )

    def _header_text(self) -> str:
        return f"**{self._config.title}**"

    def _row_text(self, index: int, row: SettingsListRow[RowValueT]) -> str:
        return f"**{index}. {row.title}**\n{row.detail}"

    def _footer_text(self) -> str:
        return f"-# Page {self._page}/{self._total_pages()}"
