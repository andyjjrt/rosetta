from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import discord
import pytest

from rosetta.commands.setting import Setting
from rosetta.utils.llm_model_access import LlmModelAccessRepository
from rosetta.utils.mcp_api_keys import McpApiKeyRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True, slots=True)
class FakeUser:
    id: int


@dataclass(frozen=True, slots=True)
class SentMessage:
    content: str | None
    ephemeral: bool
    view: discord.ui.LayoutView | None = None
    allowed_mentions: discord.AllowedMentions | None = field(
        default_factory=discord.AllowedMentions.none
    )


@dataclass(frozen=True, slots=True)
class EditCall:
    content: str | None
    view: discord.ui.LayoutView | None
    allowed_mentions: discord.AllowedMentions | None


def flatten_text(view: discord.ui.LayoutView) -> str:
    return "\n".join(
        item.content
        for item in view.walk_children()
        if isinstance(item, discord.ui.TextDisplay)
    )


ControlT = TypeVar("ControlT", bound=discord.ui.Item[discord.ui.LayoutView])


def control_by_custom_id(
    view: discord.ui.LayoutView,
    custom_id: str,
    control_type: type[ControlT],
) -> ControlT:
    for item in view.walk_children():
        if isinstance(item, control_type) and item.custom_id == custom_id:
            return item
    raise AssertionError(f"missing control {custom_id!r}")


@dataclass(frozen=True, slots=True)
class FakeResponse:
    sent: list[SentMessage] = field(default_factory=list)
    edits: list[EditCall] = field(default_factory=list)

    async def send_message(
        self,
        content: str | None = None,
        *,
        ephemeral: bool = False,
        view: discord.ui.LayoutView | None = None,
        allowed_mentions: discord.AllowedMentions | None = None,
        **_kwargs: object,
    ) -> None:
        self.sent.append(
            SentMessage(
                content=content,
                ephemeral=ephemeral,
                view=view,
                allowed_mentions=allowed_mentions,
            )
        )

    async def edit_message(
        self,
        content: str | None = None,
        *,
        view: discord.ui.LayoutView | None = None,
        allowed_mentions: discord.AllowedMentions | None = None,
        **_kwargs: object,
    ) -> None:
        self.edits.append(
            EditCall(
                content=content,
                view=view,
                allowed_mentions=allowed_mentions,
            )
        )


@dataclass(frozen=True, slots=True)
class FakeFollowup:
    sent: list[SentMessage] = field(default_factory=list)

    async def send(
        self,
        content: str | None = None,
        *,
        ephemeral: bool = False,
        view: discord.ui.LayoutView | None = None,
        allowed_mentions: discord.AllowedMentions | None = None,
        **_kwargs: object,
    ) -> None:
        self.sent.append(
            SentMessage(
                content=content,
                ephemeral=ephemeral,
                view=view,
                allowed_mentions=allowed_mentions,
            )
        )


@dataclass(frozen=True, slots=True)
class FakeClient:
    owner_id: int

    async def is_owner(self, user: FakeUser) -> bool:
        return user.id == self.owner_id


@dataclass(frozen=True, slots=True)
class FakeInteraction:
    user: FakeUser
    client: FakeClient
    response: FakeResponse = field(default_factory=FakeResponse)
    followup: FakeFollowup = field(default_factory=FakeFollowup)


def command(cog: Setting, name: str):
    llm_group = type(cog).setting_group.get_command("llm")
    assert llm_group is not None
    selected = llm_group.get_command(name)
    assert selected is not None
    return selected


def setting_cog(tmp_path: Path) -> tuple[Setting, LlmModelAccessRepository]:
    database_path = tmp_path / "settings.sqlite3"
    repository = LlmModelAccessRepository(database_path)
    cog = Setting(
        FakeClient(owner_id=1),
        mcp_api_key_repository=McpApiKeyRepository(database_path),
        model_access_repository=repository,
    )
    return cog, repository


async def test_owner_can_add_list_and_remove_llm_model_access(tmp_path: Path) -> None:
    # Given: the owner manages an empty LLM model-selection allowlist.
    cog, repository = setting_cog(tmp_path)
    interaction = FakeInteraction(user=FakeUser(1), client=FakeClient(owner_id=1))

    # When: one Discord user is added, listed, and removed.
    await command(cog, "add").callback(cog, interaction, user_id="123")
    add_message = interaction.response.sent[-1]
    created_at = (await repository.list())[0].created_at
    await command(cog, "list").callback(cog, interaction)
    list_message = interaction.response.sent[-1]
    await command(cog, "remove").callback(cog, interaction, user_id="123")
    remove_message = interaction.response.sent[-1]

    # Then: each response is private and the final grant is revoked.
    assert (
        add_message.content == "Granted LLM model selection access to <@123> (`123`)."
    )
    assert add_message.ephemeral is True
    assert list_message.content is None
    assert list_message.view is not None
    list_text = flatten_text(list_message.view)
    assert "<@123>" in list_text
    assert "`123`" in list_text
    assert created_at in list_text
    assert list_message.ephemeral is True
    assert list_message.allowed_mentions is not None
    assert list_message.allowed_mentions.to_dict() == {"parse": []}
    assert interaction.followup.sent == []
    assert remove_message.content == (
        "Removed LLM model selection access from <@123> (`123`)."
    )
    assert remove_message.ephemeral is True
    assert await repository.is_allowed(123) is False


def test_layout_view_helpers_find_text_and_controls_without_child_indices() -> None:
    view = discord.ui.LayoutView()
    view.add_item(discord.ui.TextDisplay("first"))
    view.add_item(discord.ui.Button(label="Action", custom_id="settings:action"))
    view.add_item(discord.ui.TextDisplay("second"))

    assert flatten_text(view) == "first\nsecond"
    assert (
        control_by_custom_id(view, "settings:action", discord.ui.Button).label
        == "Action"
    )
    with pytest.raises(AssertionError, match="missing control"):
        control_by_custom_id(view, "settings:missing", discord.ui.Button)


@pytest.mark.anyio
async def test_layout_view_edit_recorder_preserves_view_and_mention_policy() -> None:
    view = discord.ui.LayoutView()
    response = FakeResponse()
    allowed_mentions = discord.AllowedMentions.none()

    await response.edit_message(
        view=view,
        allowed_mentions=allowed_mentions,
        extra_kwarg="accepted",
    )
    await response.edit_message(content="updated", view=view)

    assert response.edits[0].content is None
    assert response.edits[0].view is view
    assert response.edits[0].allowed_mentions is allowed_mentions
    assert response.edits[0].allowed_mentions.to_dict() == {"parse": []}
    assert response.edits[1].content == "updated"
    assert response.edits[1].view is view


async def test_non_owner_cannot_mutate_llm_model_access(tmp_path: Path) -> None:
    # Given: a non-owner invokes the LLM access add command.
    cog, repository = setting_cog(tmp_path)
    interaction = FakeInteraction(user=FakeUser(2), client=FakeClient(owner_id=1))

    # When: the command callback runs.
    await command(cog, "add").callback(cog, interaction, user_id="123")

    # Then: the private denial leaves the allowlist unchanged.
    sent = interaction.response.sent[-1]
    assert sent.ephemeral is True
    assert sent.content is not None
    assert "owner" in sent.content.lower()
    assert await repository.list() == []


async def test_llm_access_list_empty_has_contentless_ephemeral_view(
    tmp_path: Path,
) -> None:
    # Given: the owner manages an empty allowlist.
    cog, _repository = setting_cog(tmp_path)
    interaction = FakeInteraction(user=FakeUser(1), client=FakeClient(owner_id=1))

    # When: the owner lists model-selection grants.
    await command(cog, "list").callback(cog, interaction)

    # Then: one private contentless view contains the exact empty state.
    assert len(interaction.response.sent) == 1
    message = interaction.response.sent[0]
    assert message.content is None
    assert message.ephemeral is True
    assert isinstance(message.view, discord.ui.LayoutView)
    assert message.allowed_mentions is not None
    assert message.allowed_mentions.to_dict() == {"parse": []}
    empty_text = flatten_text(message.view)
    assert "No users have LLM model selection access." in empty_text
    assert "-# Page 1/1" in empty_text
    assert interaction.followup.sent == []


async def test_llm_access_list_paginates_ordered_users_with_mention_suppression(
    tmp_path: Path,
) -> None:
    # Given: 60 grants exist in repository/display order.
    cog, repository = setting_cog(tmp_path)
    for user_id in range(1000, 1060):
        await repository.add(user_id)
    owner = FakeClient(owner_id=1)
    interaction = FakeInteraction(user=FakeUser(1), client=owner)

    # When: the owner lists grants and follows every next-page control.
    await command(cog, "list").callback(cog, interaction)
    assert len(interaction.response.sent) == 1
    initial = interaction.response.sent[0]
    assert initial.content is None
    assert initial.view is not None
    assert initial.ephemeral is True
    assert initial.allowed_mentions is not None
    assert initial.allowed_mentions.to_dict() == {"parse": []}

    page_texts = [flatten_text(initial.view)]
    current_view = initial.view
    for _page in range(1, 12):
        view = current_view
        next_button = control_by_custom_id(
            view,
            "settings:llm:next",
            discord.ui.Button,
        )
        page_interaction = FakeInteraction(user=FakeUser(1), client=owner)
        await next_button.callback(page_interaction)
        assert len(page_interaction.response.edits) == 1
        edit = page_interaction.response.edits[0]
        assert edit.content is None
        assert edit.view is view
        assert edit.allowed_mentions is not None
        assert edit.allowed_mentions.to_dict() == {"parse": []}
        assert page_interaction.followup.sent == []
        page_texts.append(flatten_text(view))

    # Then: every rendered page has the expected footer and exact row sequence.
    assert len(page_texts) == 12
    assert "-# Page 1/12" in page_texts[0]
    assert "-# Page 12/12" in page_texts[-1]
    rendered_ids = [
        int(match.group(1))
        for page_text in page_texts
        for match in re.finditer(r"\*\*\d+\. <@(\d+)>\*\*", page_text)
    ]
    assert rendered_ids == list(range(1000, 1060))
    assert len(rendered_ids) == len(set(rendered_ids)) == 60
    assert interaction.followup.sent == []


async def test_llm_access_list_non_owner_cannot_paginate(tmp_path: Path) -> None:
    # Given: the owner has opened a multi-page allowlist view.
    cog, repository = setting_cog(tmp_path)
    for user_id in range(1000, 1010):
        await repository.add(user_id)
    owner = FakeClient(owner_id=1)
    owner_interaction = FakeInteraction(user=FakeUser(1), client=owner)
    await command(cog, "list").callback(cog, owner_interaction)
    view = owner_interaction.response.sent[0].view
    assert view is not None
    page_before = flatten_text(view)
    next_button = control_by_custom_id(view, "settings:llm:next", discord.ui.Button)

    # When: a non-owner invokes the current next-page callback.
    non_owner_interaction = FakeInteraction(user=FakeUser(2), client=owner)
    await next_button.callback(non_owner_interaction)

    # Then: denial is private and neither state nor the view is edited.
    assert len(non_owner_interaction.response.sent) == 1
    denial = non_owner_interaction.response.sent[0]
    assert denial.ephemeral is True
    assert denial.content is not None
    assert "owner" in denial.content.lower()
    assert non_owner_interaction.response.edits == []
    assert non_owner_interaction.followup.sent == []
    assert flatten_text(view) == page_before


@pytest.mark.parametrize("user_id", ("", "abc", "0", "-1"))
async def test_llm_access_commands_reject_invalid_discord_user_ids(
    tmp_path: Path,
    user_id: str,
) -> None:
    # Given: the owner supplies a non-snowflake user ID.
    cog, repository = setting_cog(tmp_path)
    interaction = FakeInteraction(user=FakeUser(1), client=FakeClient(owner_id=1))

    # When: the add command parses the ID boundary.
    await command(cog, "add").callback(cog, interaction, user_id=user_id)

    # Then: validation fails privately without a database grant.
    sent = interaction.response.sent[-1]
    assert sent.ephemeral is True
    assert sent.content is not None
    assert "positive integer" in sent.content
    assert await repository.list() == []
