
import discord
from discord.ext import commands

from rosetta.utils.embeds import ErrorEmbed, SuccessEmbed


class GuildsView(discord.ui.LayoutView):
    def __init__(self, bot: commands.Bot, user: discord.User | discord.Member, accent_color: int = 0x229AE0):
        super().__init__(timeout=300)
        self.bot = bot
        self.user = user
        self.accent_color = accent_color
        self.page_size = 5
        self.container = self.construct_container()
        self.add_item(self.container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "You cannot interact with this view.", ephemeral=True
            )
            return False
        return True

    def refresh_item(self, old_item: discord.ui.Item, new_item: discord.ui.Item):
        new_item._update_view(self)
        self._swap_item(old_item, new_item, "")
        del old_item

    def get_sorted_guilds(self):
        return sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True)

    def pagination_callback(self, current_page: int = 1):
        async def _callback(interaction: discord.Interaction):
            guilds = self.get_sorted_guilds()
            total_pages = (len(guilds) + self.page_size - 1) // self.page_size
            new_page = current_page

            if interaction.data["custom_id"] == "next":
                new_page = min(current_page + 1, total_pages)
            elif interaction.data["custom_id"] == "previous":
                new_page = max(current_page - 1, 1)

            new_container = self.construct_container(new_page)
            self.refresh_item(self.container, new_container)
            self.container = new_container

            await interaction.response.edit_message(view=self)

        return _callback

    def leave_callback(self, guild_id: int, guild_name: str):
        async def _callback(interaction: discord.Interaction):
            is_owner = await self.bot.is_owner(interaction.user)
            if not is_owner:
                await interaction.response.send_message(
                    embed=ErrorEmbed(
                        user=interaction.user,
                        error="Only the bot owner can use this action.",
                    ),
                    ephemeral=True,
                )
                return
            target_guild = self.bot.get_guild(guild_id)
            if target_guild:
                await target_guild.leave()
                await interaction.response.send_message(
                    embed=SuccessEmbed(
                        user=interaction.user,
                        message=f"Left guild **{guild_name}** (`{guild_id}`)",
                    ),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    embed=ErrorEmbed(
                        user=interaction.user,
                        error=f"Guild **{guild_name}** (`{guild_id}`) not found",
                    ),
                    ephemeral=True,
                )

        return _callback

    def construct_container(self, page: int = 1):
        guilds = self.get_sorted_guilds()
        total_guilds = len(guilds)
        total_users = sum(g.member_count or 0 for g in guilds)
        total_pages = (total_guilds + self.page_size - 1) // self.page_size

        # Header
        header = discord.ui.TextDisplay(
            f"🏠 **Bot Guilds**\n"
            f"Currently in **{total_guilds}** guilds with **{total_users:,}** total users"
        )

        container = discord.ui.Container(
            header,
            discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small),
            accent_color=self.accent_color,
        )

        # Paginated guild list
        start_idx = (page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, total_guilds)
        page_guilds = guilds[start_idx:end_idx]

        for i, guild in enumerate(page_guilds, start=start_idx + 1):
            owner = guild.owner.name if guild.owner else "Unknown"
            guild_info = discord.ui.TextDisplay(
                f"**{i}.** {guild.name}\n"
                f"ID: `{guild.id}`\n"
                f"Members: **{guild.member_count:,}** | Owner: {owner}"
            )
            leave_btn = discord.ui.Button(
                label="Leave",
                custom_id=f"leave_{guild.id}",
                style=discord.ButtonStyle.danger,
            )
            leave_btn.callback = self.leave_callback(guild.id, guild.name)
            section = discord.ui.Section(guild_info, accessory=leave_btn)
            container.add_item(section)
            if i < end_idx:
                container.add_item(
                    discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small)
                )

        # Footer with page info
        container.add_item(
            discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small)
        )
        footer = discord.ui.TextDisplay(f"-# Page {page}/{total_pages}")
        container.add_item(footer)

        if total_pages > 1:
            actionrow = discord.ui.ActionRow()
            previous_button = discord.ui.Button(
                label="Previous", custom_id="previous", disabled=page <= 1
            )
            previous_button.callback = self.pagination_callback(page)
            actionrow.add_item(previous_button)

            next_button = discord.ui.Button(
                label="Next", custom_id="next", disabled=page >= total_pages
            )
            next_button.callback = self.pagination_callback(page)
            actionrow.add_item(next_button)

            container.add_item(actionrow)

        return container
