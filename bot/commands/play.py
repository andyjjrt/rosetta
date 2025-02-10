from typing import List
import discord
from discord import (
    Bot,
    option,
    ApplicationContext,
)
from discord.ext import commands
from data.track import Track
from data.subscriptions import Subscription, Queue
from utils.embeds import SuccessEmbed, SearchEmbed, LeaveEmbed
from queue import Empty
import yt_dlp
import os, random, asyncio
from spotdl import Downloader
from spotdl.utils.search import get_simple_songs


class Player(commands.Cog):
    subscriptions = Subscription()

    def __init__(self, bot: Bot):
        self.bot = bot

    async def _play(self, ctx: ApplicationContext, url: str, loop: str, shuffle: bool):
        try:
            tracks = await Track.from_url(url, ctx.author)
        except Exception as e:
            raise commands.CommandError(f"[yt-dlp] {e}")

        if ctx.voice_client is None:
            await ctx.author.voice.channel.connect()

        if shuffle:
            random.shuffle(tracks["tracks"])

        subscription = self.subscriptions.get(ctx.guild_id)
        if subscription:
            subscription.addTracks(tracks["tracks"])
        else:
            self.subscriptions.createQueue(
                self.bot,
                ctx.guild_id,
                ctx.channel,
                ctx.voice_client,
                tracks["tracks"],
                loop,
            )
        embed = SuccessEmbed(
            self.bot, f"Enqueued [**{tracks['title']}**]({tracks['url']})"
        )
        embed.set_thumbnail(url=tracks["thumbnail"])
        return embed

    async def _search(self, ctx: ApplicationContext, keyword: str):
        options = {
            "extractor_retries": 1,
            "quiet": True,
            "ignoreerrors": True,
            "extract_flat": True,
        }
        with yt_dlp.YoutubeDL(options) as ytdl:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(f"ytsearch25:{keyword}", download=False)
            )
            data = data["entries"]
            tracks = [Track(d, ctx.author) for d in data]
            return tracks

    @commands.slash_command(description="Play Youtube music")
    @option("url", description="url")
    @option(
        "loop",
        description="loop",
        choices=["Off", "One", "Queue"],
        required=False,
        default="Off",
    )
    @option("shuffle", type=bool, required=False)
    async def play(self, ctx: ApplicationContext, url: str, loop: str, shuffle: bool):
        await ctx.defer()
        embed = await self._play(ctx, url, loop, shuffle)
        await ctx.respond(embed=embed)

    @commands.slash_command(description="Set loop")
    @option(
        "loop",
        description="loop",
        choices=["Off", "One", "Queue"],
        default="Off",
        required=True,
    )
    async def loop(self, ctx: ApplicationContext, loop: str):
        subscription = self.subscriptions.get(ctx.guild_id)
        subscription.loop = loop
        await ctx.respond(
            embed=SuccessEmbed(self.bot, f"Current loop: **{subscription.loop}**")
        )

    @commands.slash_command(description="Search in Youtube")
    @option("keyword", description="keyword")
    async def search(self, ctx: ApplicationContext, keyword: str):

        await ctx.defer()
        tracks = await self._search(ctx, keyword)
        await ctx.respond(
            embed=SearchEmbed(self.bot, keyword, tracks),
            view=SearchSelectView(self, tracks, ctx),
        )

    @commands.slash_command(description="Shuffle")
    async def shuffle(self, ctx: ApplicationContext):
        subscription = self.subscriptions.get(ctx.guild_id)
        random.shuffle(subscription.queue)
        await ctx.respond(embed=SuccessEmbed(self.bot, f"Shuffle complete"))

    @commands.slash_command(description="Skip to next song")
    async def skip(self, ctx: ApplicationContext):
        await ctx.defer()
        subscription = self.subscriptions.get(ctx.guild_id)
        try:
            track = await subscription.skip()
            embed = SuccessEmbed(
                self.bot, f"Skipped to [**{track.title}**]({track.url})"
            )
            embed.set_thumbnail(url=track.thumbnail)
            await ctx.followup.send(embed=embed)
        except Empty:
            await ctx.followup.send(embed=SuccessEmbed(self.bot, f"No song left"))

    @commands.slash_command(description="Leave current channel")
    async def leave(self, ctx: ApplicationContext):
        subscription = self.subscriptions.get(ctx.guild_id)
        await subscription.leave(message=False)
        await ctx.respond(embed=LeaveEmbed(self.bot))

    @play.before_invoke
    async def ensure_voice(self, ctx: ApplicationContext):
        if ctx.voice_client is None:
            if not ctx.author.voice:
                raise commands.CommandError("You are not connected to a voice channel.")
        subscription = self.subscriptions.get(ctx.guild_id)
        if subscription and not type(subscription) == Queue:
            raise commands.CommandError("You are not using music feature.")

    @loop.before_invoke
    @skip.before_invoke
    @leave.before_invoke
    async def ensure_subscription(self, ctx: ApplicationContext):
        subscription = self.subscriptions.get(ctx.guild_id)
        if not subscription:
            raise commands.CommandError("You are not connected to a voice channel.")
        elif subscription and not type(subscription) == Queue:
            raise commands.CommandError("You are not using music feature.")

    @commands.Cog.listener("on_voice_state_update")
    async def test(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        print(before.channel, after.channel)
        if before.channel:
            subscription = self.subscriptions.get(before.channel.guild.id)
            if subscription:
                if member != self.bot:
                    if len(before.channel.members) == 1:
                        print("Im lonly")
    

class SearchSelectView(discord.ui.View):
    def __init__(
        self,
        player: Player,
        tracks: List[Track],
        ctx: ApplicationContext,
        *,
        timeout=60,
    ):
        super().__init__(timeout=timeout)
        self.add_item(SearchSelect(player, tracks, ctx))
        self.add_item(SearchButton(player, tracks, ctx, label="Search", emoji="🔎"))


class SearchModal(discord.ui.Modal):
    def __init__(
        self, player: Player, tracks: List[Track], ctx: ApplicationContext
    ) -> None:
        super().__init__(title="Search Model")
        self.add_item(discord.ui.InputText(label="Keyword"))
        self.player = player
        self.tracks = tracks
        self.ctx = ctx

    async def callback(self, interaction: discord.Interaction):
        _ctx = ApplicationContext(self.player.bot, interaction)
        keyword = self.children[0].value
        tracks = await self.player._search(_ctx, keyword)
        await interaction.message.edit(
            embed=SearchEmbed(self.player.bot, keyword, tracks),
            view=SearchSelectView(self.player, tracks, _ctx),
        )
        await interaction.response.send_message(
            embed=SuccessEmbed(self.player.bot, f'Searched for "{keyword}"'),
            ephemeral=True,
        )


class SearchSelect(discord.ui.Select):
    def __init__(self, player: Player, tracks: List[Track], ctx: ApplicationContext):
        options = [
            discord.SelectOption(
                label=track.title,
                emoji="🎵",
                description=track.channel,
                value=track.url,
            )
            for track in tracks
        ]
        super().__init__(
            placeholder="Select an option", max_values=1, min_values=1, options=options
        )
        self.player = player
        self.tracks = tracks
        self.ctx = ctx

    async def callback(self, interaction: discord.Interaction):
        _ctx = ApplicationContext(self.player.bot, interaction)
        self.view.clear_items()
        await interaction.message.edit(view=self.view)

        await self.player.ensure_voice(_ctx)
        message = await interaction.response.send_message(
            embed=SuccessEmbed(self.player.bot, "fetching...")
        )
        embed = await self.player._play(_ctx, self.values[0], False, False)
        await message.edit(embed=embed)


class SearchButton(discord.ui.Button):
    def __init__(
        self,
        player: Player,
        tracks: List[Track],
        ctx: ApplicationContext,
        *,
        style=discord.ButtonStyle.primary,
        label=None,
        emoji=None,
    ):
        super().__init__(style=style, label=label, emoji=emoji)
        self.player = player
        self.tracks = tracks
        self.ctx = ctx

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            SearchModal(self.player, self.tracks, self.ctx)
        )
