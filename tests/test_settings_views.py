from __future__ import annotations

from dataclasses import dataclass, field

import discord
import pytest

from rosetta.utils.views.Settings import (
    SettingsListConfig,
    SettingsListRow,
    SettingsListView,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True, slots=True)
class FakeUser:
    id: int


@dataclass(frozen=True, slots=True)
class EditCall:
    view: discord.ui.LayoutView
    allowed_mentions: discord.AllowedMentions | None


@dataclass(frozen=True, slots=True)
class SentMessage:
    content: str | None
    ephemeral: bool


@dataclass(slots=True)
class FakeResponse:
    sent: list[SentMessage] = field(default_factory=list)
    edits: list[EditCall] = field(default_factory=list)

    async def send_message(
        self,
        content: str | None = None,
        *,
        ephemeral: bool = False,
        allowed_mentions: discord.AllowedMentions | None = None,
    ) -> None:
        self.sent.append(SentMessage(content=content, ephemeral=ephemeral))

    async def edit_message(
        self,
        *,
        view: discord.ui.LayoutView,
        allowed_mentions: discord.AllowedMentions | None = None,
    ) -> None:
        self.edits.append(EditCall(view=view, allowed_mentions=allowed_mentions))


@dataclass(slots=True)
class FakeInteraction:
    user: FakeUser
    custom_id: str
    response: FakeResponse = field(default_factory=FakeResponse)

    @property
    def data(self) -> dict[str, str]:
        return {"custom_id": self.custom_id}


@dataclass(slots=True)
class OwnerChecker:
    owner_id: int
    checked: list[int] = field(default_factory=list)

    async def __call__(self, interaction: FakeInteraction) -> bool:
        self.checked.append(interaction.user.id)
        return interaction.user.id == self.owner_id


def rows(count: int) -> tuple[SettingsListRow[str], ...]:
    return tuple(
        SettingsListRow(
            title=f"Setting {index}", detail=f"Value {index}", value=str(index)
        )
        for index in range(1, count + 1)
    )


def make_view(
    *,
    row_count: int,
    checker: OwnerChecker | None = None,
) -> SettingsListView[str]:
    return SettingsListView(
        SettingsListConfig(
            title="Settings",
            rows=rows(row_count),
            empty_message="No settings configured.",
            owner_check=checker or OwnerChecker(owner_id=10),
            custom_id_prefix="settings:test",
            accent=0x229AE0,
        )
    )


def flatten_text(view: SettingsListView[str]) -> str:
    return "\n".join(view.visible_text())


def buttons(
    view: SettingsListView[str],
) -> dict[str, discord.ui.Button[SettingsListView[str]]]:
    return {
        item.custom_id: item
        for item in view.walk_children()
        if isinstance(item, discord.ui.Button) and item.custom_id is not None
    }


async def test_page_one_renders_five_rows_and_conditional_buttons() -> None:
    # Given: six rows and the default page size.
    view = make_view(row_count=6)

    # When: the page-one text and buttons are inspected.
    text = flatten_text(view)
    controls = buttons(view)

    # Then: only rows 1-5 are visible, Previous is disabled, and Next is enabled.
    assert "**Settings**" in text
    assert "**1. Setting 1**" in text
    assert "Value 5" in text
    assert "Setting 6" not in text
    assert "Page 1/2" in text
    assert controls["settings:test:previous"].disabled is True
    assert controls["settings:test:next"].disabled is False


async def test_empty_state_keeps_page_one_of_one_without_buttons() -> None:
    # Given: a settings list with no rows.
    view = make_view(row_count=0)

    # When: the rendered page is inspected.
    text = flatten_text(view)

    # Then: the empty state and Page 1/1 are visible without pagination controls.
    assert "No settings configured." in text
    assert "Page 1/1" in text
    assert buttons(view) == {}


async def test_pagination_rechecks_owner_and_suppresses_mentions_on_edit() -> None:
    # Given: an authorized owner opens a paginated settings list.
    checker = OwnerChecker(owner_id=10)
    view = make_view(row_count=6, checker=checker)
    interaction = FakeInteraction(FakeUser(id=10), "settings:test:next")

    # When: the owner clicks Next.
    await view.go_next(interaction)

    # Then: authorization is rechecked, page two is rebuilt, and edits suppress mentions.
    assert checker.checked == [10]
    assert "**6. Setting 6**" in flatten_text(view)
    assert len(interaction.response.edits) == 1
    edit = interaction.response.edits[0]
    assert edit.view is view
    assert edit.allowed_mentions is not None
    assert edit.allowed_mentions.to_dict() == {"parse": []}


async def test_unauthorized_pagination_denies_ephemerally_without_edit() -> None:
    # Given: a non-owner tries to paginate an owner-only settings list.
    checker = OwnerChecker(owner_id=10)
    view = make_view(row_count=6, checker=checker)
    interaction = FakeInteraction(FakeUser(id=99), "settings:test:next")

    # When: the callback runs.
    await view.go_next(interaction)

    # Then: the interaction is denied privately and the message is not edited.
    assert checker.checked == [99]
    assert interaction.response.sent[-1].ephemeral is True
    assert interaction.response.edits == []
    assert "**1. Setting 1**" in flatten_text(view)


async def test_stale_page_rebuild_clamps_to_last_available_page() -> None:
    # Given: a stale view currently showing page two.
    view = make_view(row_count=6)
    await view.go_next(FakeInteraction(FakeUser(id=10), "settings:test:next"))

    # When: the underlying rows shrink below the current page.
    view.replace_rows(rows(3))

    # Then: the view rebuilds to the only valid page.
    assert "**1. Setting 1**" in flatten_text(view)
    assert "Page 1/1" in flatten_text(view)
    assert buttons(view) == {}


def test_malformed_input_rejects_empty_prefix_and_page_size() -> None:
    # Given / When / Then: invalid construction data is rejected at the boundary.
    with pytest.raises(ValueError, match="custom_id_prefix"):
        SettingsListConfig(
            title="Settings",
            rows=(),
            empty_message="Empty",
            owner_check=OwnerChecker(owner_id=10),
            custom_id_prefix=" ",
        )

    with pytest.raises(ValueError, match="page_size"):
        SettingsListConfig(
            title="Settings",
            rows=(),
            empty_message="Empty",
            owner_check=OwnerChecker(owner_id=10),
            custom_id_prefix="settings:test",
            page_size=0,
        )
