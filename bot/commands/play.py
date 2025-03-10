from typing import List
import discord
from discord import (
    Bot,
    option,
    ApplicationContext,
)
from discord.ext import commands, tasks
from utils.track import Track
from utils.subscriptions import Subscription, Queue
from utils.embeds import (
    SuccessEmbed,
    SearchEmbed,
    LeaveEmbed,
    InfoEmbed,
    ErrorEmbed,
    ProcessingEmbed,
)
from queue import Empty
import yt_dlp
import os, random, asyncio
from spotdl import Downloader
from spotdl.utils.search import get_simple_songs


class Player(commands.Cog):
    subscriptions = Subscription()

    def __init__(self, bot: Bot):
        self.bot = bot

    async def _play(
        self, ctx: ApplicationContext, url: str, loop: str, shuffle: bool, top: bool
    ):
        try:
            tracks = await Track.from_url(url, ctx.author)
        except Exception as e:
            raise commands.CommandError(f"[yt-dlp] {e}")

        if ctx.voice_client is None:
            await ctx.author.voice.channel.connect()
            # Insure deafen
            await ctx.author.voice.channel.guild.change_voice_state(
                channel=ctx.author.voice.channel, self_deaf=True
            )

        if shuffle:
            random.shuffle(tracks["tracks"])

        subscription = self.subscriptions.get(ctx.guild_id)
        if subscription:
            subscription.addTracks(tracks["tracks"], top)
        else:
            self.subscriptions.createQueue(
                self.bot.user,
                ctx.guild_id,
                ctx.channel,
                ctx.voice_client,
                tracks["tracks"],
                loop,
            )
        embed = SuccessEmbed(
            ctx.author, f"Enqueued [**{tracks['title']}**]({tracks['url']})"
        )
        embed.set_thumbnail(url=tracks["thumbnail"])
        return embed

    async def _search(self, ctx: ApplicationContext, keyword: str):
        options = {
            "extractor_retries": 1,
            "quiet": True,
            "noplaylist": True,
            "ignoreerrors": True,
            "extract_flat": True,
        }
        with yt_dlp.YoutubeDL(options) as ytdl:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(
                None,
                lambda: ytdl.extract_info(f"ytsearch25:{keyword}", download=False),
            )
            data = [
                entry
                for entry in data.get("entries", [])
                if entry.get("ie_key") == "Youtube"
            ]
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
    @option("top", type=bool, required=False)
    async def play(
        self, ctx: ApplicationContext, url: str, loop: str, shuffle: bool, top: bool
    ):
        await ctx.defer()
        message = await ctx.respond(embed=ProcessingEmbed(self.bot.user))
        embed = await self._play(ctx, url, loop, shuffle, top)
        await message.edit(embed=embed)

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
            embed=SuccessEmbed(self.bot.user, f"Current loop: **{subscription.loop}**")
        )

    @commands.slash_command(description="Search in Youtube")
    @option("keyword", description="keyword")
    async def search(self, ctx: ApplicationContext, keyword: str):
        await ctx.defer()
        tracks = await self._search(ctx, keyword)
        await ctx.respond(
            embed=SearchEmbed(self.bot.user, keyword, tracks),
            view=SearchSelectView(self, tracks, ctx),
        )

    @commands.slash_command(description="Shuffle")
    async def shuffle(self, ctx: ApplicationContext):
        subscription = self.subscriptions.get(ctx.guild_id)
        random.shuffle(subscription.queue)
        await ctx.respond(embed=SuccessEmbed(self.bot.user, f"Shuffle complete"))

    @commands.slash_command(description="Skip to next song")
    async def skip(self, ctx: ApplicationContext):
        await ctx.defer()
        subscription = self.subscriptions.get(ctx.guild_id)
        try:
            track = await subscription.skip()
            embed = SuccessEmbed(
                self.bot.user, f"Skipped to [**{track.title}**]({track.url})"
            )
            embed.set_thumbnail(url=track.thumbnail)
            await ctx.followup.send(embed=embed)
        except Empty:
            await ctx.followup.send(embed=SuccessEmbed(self.bot.user, f"No song left"))

    @commands.slash_command(description="Leave current channel")
    async def leave(self, ctx: ApplicationContext):
        subscription = self.subscriptions.get(ctx.guild_id)
        await subscription.leave(message=False)
        await ctx.respond(embed=LeaveEmbed(self.bot.user))

    @commands.slash_command(description="Show the song playing now")
    async def nowplaying(self, ctx: ApplicationContext):
        await ctx.defer()
        subscription = self.subscriptions.get(ctx.guild_id)
        if not subscription.nowPlaying:
            await ctx.respond(embed=ErrorEmbed(self.bot.user, "Not playing now."))
            return
        embed = SuccessEmbed(
            self.bot.user,
            f"[**{subscription.nowPlaying.title}**]({subscription.nowPlaying.url})\n{subscription.nowPlaying.time}",
        )
        embed.set_thumbnail(url=subscription.nowPlaying.thumbnail)
        await ctx.respond(embed=embed)

    @play.before_invoke
    async def ensure_voice(self, ctx: ApplicationContext):
        if ctx.voice_client is None:
            if not ctx.author.voice:
                raise commands.CommandError("You are not connected to a voice channel.")

    @loop.before_invoke
    @skip.before_invoke
    @leave.before_invoke
    @shuffle.before_invoke
    async def ensure_subscription(self, ctx: ApplicationContext):
        await self.ensure_voice(ctx)
        subscription = self.subscriptions.get(ctx.guild_id)
        if not subscription:
            raise commands.CommandError("You are not plaing in this guild.")

    @commands.Cog.listener("on_voice_state_update")
    async def lonelyListener(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if before.channel:
            subscription = self.subscriptions.get(before.channel.guild.id)
            if subscription:
                if member != self.bot.user:
                    if len(before.channel.voice_states) == 1:
                        self.time = 0
                        self.lonelyTimer.start(subscription.voiceClient.channel)
                        await subscription.messageChannel.send(
                            embed=InfoEmbed(
                                self.bot.user,
                                ":pleading_face: Felling lonely. I'll leave in **60** seconds",
                            )
                        )
        if after.channel:
            subscription = self.subscriptions.get(after.channel.guild.id)
            if subscription:
                if member != self.bot.user:
                    if after.channel == subscription.voiceClient.channel:
                        if self.lonelyTimer.is_running():
                            self.lonelyTimer.cancel()
                            await subscription.messageChannel.send(
                                embed=InfoEmbed(
                                    self.bot.user, f"<@{member.id}> is back with me"
                                )
                            )

    @tasks.loop(seconds=1)
    async def lonelyTimer(self, channel: discord.VoiceChannel):
        self.time += 1
        if self.time >= 60:
            subscription = self.subscriptions.get(channel.guild.id)
            await subscription.leave()
            self.lonelyTimer.cancel()


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
        self.add_item(ToggleButton(emoji="🔝", custom_id="Top"))


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
        await interaction.message.edit(
            embed=InfoEmbed(self.player.bot.user, "Processing"),
        )
        tracks = await self.player._search(_ctx, keyword)
        await interaction.message.edit(
            embed=SearchEmbed(self.player.bot.user, keyword, tracks),
            view=SearchSelectView(self.player, tracks, _ctx),
        )
        await interaction.response.send_message(
            embed=SuccessEmbed(self.player.bot.user, f'Searched for "{keyword}"'),
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
        top = True if self.view.get_item("Top").style == discord.ButtonStyle.success else False
        self.view.clear_items()
        await interaction.message.edit(view=self.view)
        message = await interaction.respond(embed=ProcessingEmbed(self.player.bot.user))

        await self.player.ensure_voice(_ctx)
        embed = await self.player._play(_ctx, self.values[0], "Off", False, top)
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


class ToggleButton(discord.ui.Button):
    def __init__(
        self,
        *,
        style=discord.ButtonStyle.secondary,
        label=None,
        emoji=None,
        custom_id=None
    ):
        super().__init__(style=style, label=label, emoji=emoji, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        if self.style == discord.ButtonStyle.success:
            self.style = discord.ButtonStyle.secondary
            res = "False"
        elif self.style == discord.ButtonStyle.secondary:
            self.style = discord.ButtonStyle.success
            res = "True"
        
        await interaction.message.edit(view=self.view)
        await interaction.response.send_message(
            embed=SuccessEmbed(interaction.user, f'{self.custom_id} switched to {res}'),
            ephemeral=True,
        )
