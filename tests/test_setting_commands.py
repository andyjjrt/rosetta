from __future__ import annotations

import hashlib
import importlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

import discord
import pytest

from rosetta.commands.setting_support import build_mcp_key_list_view
from rosetta.utils.mcp_api_keys import (
    KEY_PREFIX,
    McpApiKeyMetadata,
    McpApiKeyRepository,
)
from rosetta.utils.nanobot_policy import ChannelId, GuildId, GuildPolicy
from rosetta.utils.views.Nanobot import NanobotSettingsView
from rosetta.utils.views.Settings import SettingsListView

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True, slots=True)
class FakeUser:
    id: int


@dataclass(frozen=True, slots=True)
class FakeChannel:
    id: int
    name: str
    type: discord.ChannelType = discord.ChannelType.text


@dataclass(slots=True)
class FakeGuild:
    id: int
    channels: dict[int, FakeChannel] = field(default_factory=dict)

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        return self.channels.get(channel_id)


@dataclass(frozen=True, slots=True)
class FakePermissions:
    administrator: bool = False


@dataclass(frozen=True, slots=True)
class SentMessage:
    content: str | None
    ephemeral: bool
    view: discord.ui.View | None
    allowed_mentions: discord.AllowedMentions | None


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


def numbered_row_names(text: str) -> list[str]:
    return [
        match.group(1)
        for line in text.splitlines()
        if (match := re.fullmatch(r"\*\*\d+\. ([^*]+)\*\*", line))
    ]


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


def seed_channel_select(
    select: discord.ui.ChannelSelect, channels: tuple[FakeChannel, ...]
) -> None:
    select._values = list(channels)  # noqa: SLF001 - test adapter for discord.py state


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


@dataclass(slots=True)
class FakeResponse:
    sent: list[SentMessage] = field(default_factory=list)
    edits: list[EditCall] = field(default_factory=list)

    async def send_message(
        self,
        content: str | None = None,
        *,
        ephemeral: bool = False,
        view: discord.ui.View | None = None,
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
        **kwargs: object,
    ) -> None:
        self.edits.append(
            EditCall(
                content=content,
                view=view,
                allowed_mentions=allowed_mentions,
            )
        )


@dataclass(slots=True)
class FakeClient:
    owner_id: int
    owner_checks: list[int] = field(default_factory=list)

    async def is_owner(self, user: FakeUser) -> bool:
        self.owner_checks.append(user.id)
        return user.id == self.owner_id


@dataclass(slots=True)
class FakeInteraction:
    user: FakeUser
    client: FakeClient
    guild: FakeGuild | None = None
    permissions: FakePermissions = field(default_factory=FakePermissions)
    response: FakeResponse = field(default_factory=FakeResponse)


class NanobotPolicyRepository(Protocol):
    async def get(self, guild_id: GuildId) -> GuildPolicy: ...


@dataclass(slots=True)
class CountingNanobotPolicyRepository:
    calls: list[GuildId] = field(default_factory=list)

    async def get(self, guild_id: GuildId) -> GuildPolicy:
        self.calls.append(guild_id)
        return GuildPolicy(enabled=False, channel_ids=frozenset())


@dataclass(frozen=True, slots=True)
class NanobotMutation:
    guild_id: GuildId
    operation: str
    value: str


@dataclass(slots=True)
class MutableNanobotPolicyRepository:
    policy: GuildPolicy
    mutations: list[NanobotMutation] = field(default_factory=list)

    async def get(self, guild_id: GuildId) -> GuildPolicy:
        return self.policy

    async def set_enabled(self, guild_id: GuildId, *, enabled: bool) -> None:
        self.policy = GuildPolicy(enabled=enabled, channel_ids=self.policy.channel_ids)
        self.mutations.append(NanobotMutation(guild_id, "set_enabled", str(enabled)))

    async def add_channel(self, guild_id: GuildId, channel_id: ChannelId) -> None:
        self.policy = GuildPolicy(
            enabled=self.policy.enabled,
            channel_ids=self.policy.channel_ids | frozenset({channel_id}),
        )
        self.mutations.append(NanobotMutation(guild_id, "add_channel", channel_id))

    async def remove_channel(self, guild_id: GuildId, channel_id: ChannelId) -> None:
        self.policy = GuildPolicy(
            enabled=self.policy.enabled,
            channel_ids=self.policy.channel_ids - frozenset({channel_id}),
        )
        self.mutations.append(NanobotMutation(guild_id, "remove_channel", channel_id))


def database_path(tmp_path: Path) -> Path:
    return tmp_path / "settings.sqlite3"


def setting_cog(
    *,
    mcp_repository: McpApiKeyRepository,
    nanobot_repository: NanobotPolicyRepository,
) -> object:
    try:
        module = importlib.import_module("rosetta.commands.setting")
    except ModuleNotFoundError as error:
        pytest.fail(f"expected rosetta.commands.setting module: {error}")
    return module.Setting(
        bot=FakeClient(owner_id=1),
        mcp_api_key_repository=mcp_repository,
        nanobot_policy_repository=nanobot_repository,
    )


def setting_command(cog: object, *path: str) -> object:
    command: object = type(cog).setting_group
    for name in path:
        command = command.get_command(name)
        assert command is not None, f"missing /setting {' '.join(path)} command"
    return command


def owner_interaction() -> FakeInteraction:
    client = FakeClient(owner_id=1)
    return FakeInteraction(
        user=FakeUser(id=1),
        client=client,
        guild=FakeGuild(id=10),
    )


def non_owner_interaction() -> FakeInteraction:
    client = FakeClient(owner_id=1)
    return FakeInteraction(
        user=FakeUser(id=2),
        client=client,
        guild=FakeGuild(id=10),
    )


async def test_owner_can_create_list_rotate_and_delete_mcp_keys(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: an owner invokes the /setting mcp management surface.
    repository = McpApiKeyRepository(database_path(tmp_path))
    cog = setting_cog(
        mcp_repository=repository,
        nanobot_repository=CountingNanobotPolicyRepository(),
    )
    interaction = owner_interaction()
    caplog.set_level(logging.DEBUG)

    # When: the owner creates, lists, rotates, and deletes a key.
    await setting_command(cog, "mcp", "create").callback(
        cog, interaction, name="operator"
    )
    create_message = interaction.response.sent[-1]
    created = (await repository.list())[0]
    await setting_command(cog, "mcp", "list").callback(cog, interaction)
    list_message = interaction.response.sent[-1]
    await setting_command(cog, "mcp", "rotate").callback(
        cog, interaction, name="operator"
    )
    rotate_message = interaction.response.sent[-1]
    await setting_command(cog, "mcp", "delete").callback(
        cog, interaction, name="operator"
    )
    delete_message = interaction.response.sent[-1]

    # Then: only create/rotate reveal plaintext, while list exposes metadata only.
    assert create_message.ephemeral is True
    assert create_message.content is not None
    assert "rst_mcp_" in create_message.content
    created_plaintext = create_message.content.split("`")[-2]
    assert list_message.content is None
    assert list_message.ephemeral is True
    assert isinstance(list_message.view, SettingsListView)
    assert list_message.allowed_mentions is not None
    assert list_message.allowed_mentions.to_dict() == {"parse": []}
    list_text = flatten_text(list_message.view)
    assert "operator" in list_text
    assert created.key_prefix.removeprefix("rst_mcp_") in list_text
    assert created.fingerprint in list_text
    assert created.created_at in list_text
    assert "rotated `never`" in list_text
    assert "rst_mcp_" not in list_text
    assert created_plaintext not in list_text
    assert "hash" not in list_text.lower()
    assert rotate_message.ephemeral is True
    assert rotate_message.content is not None
    assert "rst_mcp_" in rotate_message.content
    assert rotate_message.content != create_message.content
    rotated_plaintext = rotate_message.content.split("`")[-2]
    assert delete_message.content is not None
    assert "rst_mcp_" not in delete_message.content
    assert created_plaintext not in delete_message.content
    assert rotated_plaintext not in delete_message.content
    assert created_plaintext not in caplog.text
    assert rotated_plaintext not in caplog.text
    assert await repository.list() == []


@pytest.mark.parametrize(
    ("subcommand", "kwargs"),
    (
        ("create", {"name": "operator"}),
        ("list", {}),
        ("rotate", {"name": "operator"}),
        ("delete", {"name": "operator"}),
    ),
)
async def test_non_owner_mcp_subcommands_deny_ephemerally_without_db_mutation(
    tmp_path: Path,
    subcommand: str,
    kwargs: dict[str, str],
) -> None:
    # Given: a non-owner invokes one /setting mcp subcommand.
    repository = McpApiKeyRepository(database_path(tmp_path))
    cog = setting_cog(
        mcp_repository=repository,
        nanobot_repository=CountingNanobotPolicyRepository(),
    )
    interaction = non_owner_interaction()

    # When: the command callback runs.
    await setting_command(cog, "mcp", subcommand).callback(cog, interaction, **kwargs)

    # Then: the denial is private and create attempts leave the repository empty.
    sent = interaction.response.sent[-1]
    assert sent.ephemeral is True
    assert sent.content is not None
    assert "owner" in sent.content.lower()
    assert await repository.list() == []


@pytest.mark.parametrize("subcommand", ("create", "rotate", "delete"))
@pytest.mark.parametrize(
    "name",
    (f"{KEY_PREFIX}operator", f"operator_{KEY_PREFIX}backup"),
)
async def test_mcp_commands_reject_reserved_scheme_names_before_repository_mutation(
    tmp_path: Path,
    subcommand: str,
    name: str,
) -> None:
    # Given: an owner supplies a syntactically valid name containing the key scheme.
    path = database_path(tmp_path)
    cog = setting_cog(
        mcp_repository=McpApiKeyRepository(path),
        nanobot_repository=CountingNanobotPolicyRepository(),
    )
    interaction = owner_interaction()

    # When: a name-bearing MCP command validates its repository boundary.
    await setting_command(cog, "mcp", subcommand).callback(
        cog,
        interaction,
        name=name,
    )

    # Then: one clear private rejection occurs before migration or mutation.
    assert len(interaction.response.sent) == 1
    sent = interaction.response.sent[0]
    assert sent.ephemeral is True
    assert sent.content is not None
    assert "reserved" in sent.content.lower()
    assert not path.exists()


async def test_setting_nanobot_returns_owner_only_view_for_current_guild(
    tmp_path: Path,
) -> None:
    # Given: an owner invokes /setting nanobot in guild 10.
    repository = CountingNanobotPolicyRepository()
    cog = setting_cog(
        mcp_repository=McpApiKeyRepository(database_path(tmp_path)),
        nanobot_repository=repository,
    )
    guild = FakeGuild(id=10, channels={20: FakeChannel(id=20, name="general")})
    interaction = FakeInteraction(
        user=FakeUser(id=1),
        client=FakeClient(owner_id=1),
        guild=guild,
    )

    # When: the nanobot setting command callback runs.
    await setting_command(cog, "nanobot").callback(cog, interaction)

    # Then: the current guild policy backs a private Nanobot settings view.
    sent = interaction.response.sent[-1]
    assert repository.calls == [GuildId("10")]
    assert sent.content is None
    assert sent.ephemeral is True
    assert isinstance(sent.view, discord.ui.LayoutView)
    assert isinstance(sent.view, NanobotSettingsView)
    assert sent.allowed_mentions is not None
    assert sent.allowed_mentions.to_dict() == {"parse": []}
    assert flatten_text(sent.view) == (
        "**Nanobot settings**\n"
        "Status: **Disabled**\n"
        "Allowed channels: none\n"
        "-# Page 1/1"
    )


async def test_nanobot_callbacks_mutate_policy_refresh_rows_and_controls() -> None:
    # Given: an owner controls a disabled Nanobot policy with one text channel.
    repository = MutableNanobotPolicyRepository(
        GuildPolicy(enabled=False, channel_ids=frozenset({ChannelId("20")}))
    )
    guild = FakeGuild(
        id=10,
        channels={
            20: FakeChannel(id=20, name="general"),
            30: FakeChannel(id=30, name="*ops* @everyone"),
            40: FakeChannel(id=40, name="voice", type=discord.ChannelType.voice),
        },
    )
    owner = owner_interaction()
    owner.guild = guild
    view = NanobotSettingsView(
        policy_repository=repository,
        guild=guild,
        owner_check=owner.client,
        policy=repository.policy,
    )

    # When: the owner enables the policy and adds then removes mixed channels.
    enable_button = control_by_custom_id(view, "nanobot_enable", discord.ui.Button)
    assert enable_button.callback == view.enable
    await enable_button.callback(owner)
    assert repository.policy == GuildPolicy(
        enabled=True, channel_ids=frozenset({ChannelId("20")})
    )
    assert flatten_text(view).splitlines()[1] == "Status: **Enabled**"
    assert control_by_custom_id(view, "nanobot_enable", discord.ui.Button).disabled
    assert not control_by_custom_id(view, "nanobot_disable", discord.ui.Button).disabled
    assert owner.response.edits[-1].content is None
    assert owner.response.edits[-1].view is view
    assert owner.response.edits[-1].allowed_mentions.to_dict() == {"parse": []}

    add_select = control_by_custom_id(
        view, "nanobot_add_channels", discord.ui.ChannelSelect
    )
    seed_channel_select(add_select, (guild.channels[30], guild.channels[40]))
    await add_select.callback(owner)
    assert repository.policy.channel_ids == frozenset(
        {ChannelId("20"), ChannelId("30")}
    )
    rendered = flatten_text(view)
    assert "\\*ops\\*" in rendered
    assert "@everyone" not in rendered
    assert "\u200b" in rendered
    assert "voice" not in rendered
    assert owner.response.edits[-1].content is None
    assert owner.response.edits[-1].view is view
    assert owner.response.edits[-1].allowed_mentions.to_dict() == {"parse": []}

    remove_select = control_by_custom_id(
        view, "nanobot_remove_channels", discord.ui.ChannelSelect
    )
    seed_channel_select(remove_select, (guild.channels[20], guild.channels[40]))
    await remove_select.callback(owner)
    assert repository.policy.channel_ids == frozenset({ChannelId("30")})
    removed_text = flatten_text(view)
    assert "\\*ops\\*" in removed_text
    assert "@everyone" not in removed_text
    assert "\u200b" in removed_text
    assert "general" not in removed_text
    assert "-# Page 1/1" in removed_text
    assert repository.mutations == [
        NanobotMutation(GuildId("10"), "set_enabled", "True"),
        NanobotMutation(GuildId("10"), "add_channel", ChannelId("30")),
        NanobotMutation(GuildId("10"), "remove_channel", ChannelId("20")),
    ]
    assert all(
        edit.content is None and edit.view is view for edit in owner.response.edits
    )
    assert all(
        edit.allowed_mentions is not None
        and edit.allowed_mentions.to_dict() == {"parse": []}
        for edit in owner.response.edits
    )

    # When: the owner disables the policy after the channel callbacks.
    disable_button = control_by_custom_id(view, "nanobot_disable", discord.ui.Button)
    assert disable_button.callback == view.disable
    await disable_button.callback(owner)

    # Then: status, controls, and immutable channel state remain coherent.
    assert repository.policy == GuildPolicy(
        enabled=False, channel_ids=frozenset({ChannelId("30")})
    )
    assert "Status: **Disabled**" in flatten_text(view)
    assert not control_by_custom_id(view, "nanobot_enable", discord.ui.Button).disabled
    assert control_by_custom_id(view, "nanobot_disable", discord.ui.Button).disabled
    assert len(owner.response.edits) == 4
    assert repository.mutations == [
        NanobotMutation(GuildId("10"), "set_enabled", "True"),
        NanobotMutation(GuildId("10"), "add_channel", ChannelId("30")),
        NanobotMutation(GuildId("10"), "remove_channel", ChannelId("20")),
        NanobotMutation(GuildId("10"), "set_enabled", "False"),
    ]


async def test_nanobot_callback_denials_do_not_mutate_or_edit() -> None:
    # Given: an opened-user view and an administrator-only view with stable policies.
    repository = MutableNanobotPolicyRepository(
        GuildPolicy(enabled=False, channel_ids=frozenset())
    )
    guild = FakeGuild(id=10)
    opened_view = NanobotSettingsView(
        policy_repository=repository,
        guild=guild,
        policy=repository.policy,
        user=FakeUser(id=1),
    )
    non_owner = FakeInteraction(
        user=FakeUser(id=2),
        client=FakeClient(owner_id=1),
        guild=guild,
        permissions=FakePermissions(administrator=True),
    )
    non_admin = FakeInteraction(
        user=FakeUser(id=2),
        client=FakeClient(owner_id=1),
        guild=guild,
        permissions=FakePermissions(administrator=False),
    )
    admin_view = NanobotSettingsView(
        policy_repository=repository,
        guild=guild,
        policy=repository.policy,
        user=FakeUser(id=1),
    )
    before = flatten_text(opened_view)
    opened_controls_before = (
        control_by_custom_id(opened_view, "nanobot_enable", discord.ui.Button).disabled,
        control_by_custom_id(
            opened_view, "nanobot_disable", discord.ui.Button
        ).disabled,
    )
    admin_controls_before = (
        control_by_custom_id(admin_view, "nanobot_enable", discord.ui.Button).disabled,
        control_by_custom_id(admin_view, "nanobot_disable", discord.ui.Button).disabled,
    )

    # When: unauthorized users invoke callbacks directly.
    await opened_view.enable(non_owner)
    await admin_view.enable(non_admin)

    # Then: denials are private, mode-correct, and have no mutation or edit.
    assert non_owner.response.sent[-1].content == (
        "Only the administrator who opened this Nanobot settings view can change it."
    )
    assert non_admin.response.sent[-1].content == (
        "Only server administrators can change Nanobot settings."
    )
    assert all(message.ephemeral for message in non_owner.response.sent)
    assert all(message.ephemeral for message in non_admin.response.sent)
    assert non_owner.response.edits == []
    assert non_admin.response.edits == []
    assert repository.policy == GuildPolicy(enabled=False, channel_ids=frozenset())
    assert repository.mutations == []
    assert flatten_text(opened_view) == before
    assert (
        control_by_custom_id(opened_view, "nanobot_enable", discord.ui.Button).disabled,
        control_by_custom_id(
            opened_view, "nanobot_disable", discord.ui.Button
        ).disabled,
    ) == opened_controls_before
    assert flatten_text(admin_view) == before
    assert (
        control_by_custom_id(admin_view, "nanobot_enable", discord.ui.Button).disabled,
        control_by_custom_id(admin_view, "nanobot_disable", discord.ui.Button).disabled,
    ) == admin_controls_before


async def test_non_owner_setting_nanobot_denies_without_policy_read(
    tmp_path: Path,
) -> None:
    # Given: a non-owner invokes /setting nanobot.
    repository = CountingNanobotPolicyRepository()
    cog = setting_cog(
        mcp_repository=McpApiKeyRepository(database_path(tmp_path)),
        nanobot_repository=repository,
    )
    interaction = non_owner_interaction()

    # When: the command callback runs.
    await setting_command(cog, "nanobot").callback(cog, interaction)

    # Then: the denial is private and Nanobot policy is not read.
    sent = interaction.response.sent[-1]
    assert sent.ephemeral is True
    assert sent.content is not None
    assert "owner" in sent.content.lower()
    assert repository.calls == []


async def test_owner_setting_nanobot_without_guild_denies_without_policy_read(
    tmp_path: Path,
) -> None:
    # Given: the owner invokes /setting nanobot outside a guild.
    repository = CountingNanobotPolicyRepository()
    cog = setting_cog(
        mcp_repository=McpApiKeyRepository(database_path(tmp_path)),
        nanobot_repository=repository,
    )
    interaction = FakeInteraction(
        user=FakeUser(id=1),
        client=FakeClient(owner_id=1),
    )

    # When: the command callback runs.
    await setting_command(cog, "nanobot").callback(cog, interaction)

    # Then: the unchanged private guild denial precedes any policy read.
    sent = interaction.response.sent[-1]
    assert interaction.client.owner_checks == [1]
    assert sent.content == "Nanobot settings are only available in a server."
    assert sent.ephemeral is True
    assert sent.view is None
    assert repository.calls == []


async def test_nanobot_settings_command_is_absent_from_nanobot_group() -> None:
    # Given: Nanobot settings moved under /setting nanobot.
    from rosetta.commands.nanobot import Nanobot
    from rosetta.commands.setting import Setting

    # When / Then: /setting exists and the legacy /nanobot settings command is absent.
    assert Setting.setting_group.name == "setting"
    assert Setting.setting_group.get_command("nanobot") is not None
    assert Nanobot.nanobot_group.get_command("settings") is None
    assert not hasattr(Nanobot, "settings")


async def test_list_response_never_displays_plaintext_or_stored_hash(
    tmp_path: Path,
) -> None:
    # Given: an owner already created a key and then invokes /setting mcp list.
    repository = McpApiKeyRepository(database_path(tmp_path))
    created = await repository.create("operator")
    cog = setting_cog(
        mcp_repository=repository,
        nanobot_repository=CountingNanobotPolicyRepository(),
    )
    interaction = owner_interaction()

    # When: keys are listed through Discord.
    await setting_command(cog, "mcp", "list").callback(cog, interaction)

    # Then: the response omits both plaintext and the full stored hash.
    sent = interaction.response.sent[-1]
    full_hash = hashlib.sha256(created.plaintext_key.encode("ascii")).hexdigest()
    assert sent.content is None
    assert isinstance(sent.view, SettingsListView)
    text = flatten_text(sent.view)
    assert created.plaintext_key not in text
    assert full_hash not in text
    assert "rst_mcp_" not in text
    assert "key_hash" not in text
    assert created.fingerprint in text


async def test_mcp_list_sanitizes_legacy_reserved_names_in_all_row_paths() -> None:
    # Given: legacy metadata contains reserved tokens at the start and mid-name.
    plaintext_sentinel = f"{KEY_PREFIX}legacy-plaintext-sentinel"
    full_hash = hashlib.sha256(plaintext_sentinel.encode("ascii")).hexdigest()
    keys = tuple(
        McpApiKeyMetadata(
            name=name,
            key_prefix=f"{KEY_PREFIX}prefix{index}",
            fingerprint=f"fingerprint{index}",
            created_at=f"2026-08-0{index} 00:00:00",
            rotated_at=None,
        )
        for index, name in enumerate(
            (
                f"{KEY_PREFIX}operator",
                f"team_{KEY_PREFIX}backup",
                "alpha",
                "bravo",
                f"{KEY_PREFIX}dual_{KEY_PREFIX}name",
                "normal-operator",
            ),
            start=1,
        )
    )
    view = build_mcp_key_list_view(keys)

    # When: every rendered page and every retained row field are flattened.
    page_texts = [flatten_text(view)]
    next_button = control_by_custom_id(view, "settings:mcp:next", discord.ui.Button)
    page_interaction = owner_interaction()
    await next_button.callback(page_interaction)
    page_texts.append(flatten_text(view))
    retained_fields = tuple(
        field
        for row in view._rows  # noqa: SLF001 - retained-row secrecy contract
        for field in (row.title, row.detail, row.value)
    )

    # Then: legacy names stay recognizable without exposing reserved or secret tokens.
    inspected = (*page_texts, *retained_fields)
    for sensitive_value in (
        plaintext_sentinel,
        full_hash,
        "key_hash",
        KEY_PREFIX,
    ):
        assert all(sensitive_value not in value for value in inspected)
    assert "[reserved-prefix]operator" in inspected
    assert "team_[reserved-prefix]backup" in inspected
    assert "[reserved-prefix]dual_[reserved-prefix]name" in inspected
    assert "normal-operator" in inspected
    normal_row = view._rows[-1]  # noqa: SLF001 - retained-row behavior contract
    assert normal_row.title == normal_row.value == "normal-operator"


async def test_mcp_list_empty_state_is_contentless_ephemeral_layout_view(
    tmp_path: Path,
) -> None:
    # Given: an owner invokes MCP list against a real empty repository.
    repository = McpApiKeyRepository(database_path(tmp_path))
    cog = setting_cog(
        mcp_repository=repository,
        nanobot_repository=CountingNanobotPolicyRepository(),
    )
    interaction = owner_interaction()

    # When: the real command callback lists the empty repository.
    await setting_command(cog, "mcp", "list").callback(cog, interaction)

    # Then: the old empty-state meaning is rendered in a private contentless view.
    sent = interaction.response.sent[-1]
    assert sent.content is None
    assert sent.ephemeral is True
    assert isinstance(sent.view, discord.ui.LayoutView)
    assert isinstance(sent.view, SettingsListView)
    assert sent.allowed_mentions is not None
    assert sent.allowed_mentions.to_dict() == {"parse": []}
    assert flatten_text(sent.view) == (
        "**MCP API keys**\nNo MCP API keys have been created.\n-# Page 1/1"
    )


async def test_mcp_list_paginates_sorted_keys_with_private_owner_checked_callbacks(
    tmp_path: Path,
) -> None:
    # Given: six real keys created in deliberately non-sorted insertion order.
    repository = McpApiKeyRepository(database_path(tmp_path))
    names = ["zulu", "alpha", "echo", "bravo", "foxtrot", "charlie"]
    plaintext_by_name: dict[str, str] = {}
    full_hash_by_name: dict[str, str] = {}
    for name in names:
        created = await repository.create(name)
        plaintext_by_name[name] = created.plaintext_key
        full_hash_by_name[name] = hashlib.sha256(
            created.plaintext_key.encode("ascii")
        ).hexdigest()
    cog = setting_cog(
        mcp_repository=repository,
        nanobot_repository=CountingNanobotPolicyRepository(),
    )
    interaction = owner_interaction()

    # When: the real command callback renders page one, then an authorized Next.
    await setting_command(cog, "mcp", "list").callback(cog, interaction)
    sent = interaction.response.sent[-1]
    assert isinstance(sent.view, SettingsListView)
    view = sent.view
    page_one = flatten_text(view)
    next_button = control_by_custom_id(view, "settings:mcp:next", discord.ui.Button)
    authorized_next = owner_interaction()
    await next_button.callback(authorized_next)
    page_two = flatten_text(view)

    # Then: repository ordering, pagination, edit policy, and privacy hold globally.
    assert numbered_row_names(page_one) == sorted(names)[:5]
    assert numbered_row_names(page_two) == sorted(names)[5:]
    assert "Page 2/2" in page_two
    assert set(names) == {
        name for name in names if name in page_one or name in page_two
    }
    for name in names:
        assert (page_one + page_two).count(name) == 1
        assert plaintext_by_name[name] not in page_one + page_two
        assert full_hash_by_name[name] not in page_one + page_two
    assert "key_hash" not in page_one + page_two
    assert "rst_mcp_" not in page_one + page_two
    assert len(authorized_next.response.edits) == 1
    edit = authorized_next.response.edits[0]
    assert edit.content is None
    assert edit.view is view
    assert edit.allowed_mentions is not None
    assert edit.allowed_mentions.to_dict() == {"parse": []}

    # When: a non-owner presses the same Next callback from page two.
    non_owner_next = non_owner_interaction()
    await next_button.callback(non_owner_next)

    # Then: denial is private, no edit occurs, and page two remains unchanged.
    denial = non_owner_next.response.sent[-1]
    assert non_owner_next.client.owner_checks == [2]
    assert denial.ephemeral is True
    assert denial.content is not None
    assert "original settings owner" in denial.content
    assert non_owner_next.response.edits == []
    assert flatten_text(view) == page_two
