from discord import (
    Bot,
    option,
    ApplicationContext,
)
from discord.ext import commands
from data.track import Track
from data.subscriptions import ServerQueue
from utils.embeds import SuccessEmbed, ErrorEmbed, LeaveEmbed
from queue import Empty
import os, random

TEST_GUILDID = os.getenv("TEST_GUILDID")


class Player(commands.Cog):
    subscriptions = ServerQueue()
    
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.slash_command(guild_ids=[TEST_GUILDID], description="Play music")
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
        
        if ctx.voice_client is None:
            await ctx.author.voice.channel.connect()
        tracks = await Track.from_url(url, ctx.author)
        subscription = self.subscriptions.getQueue(ctx.guild_id)
        
        if shuffle:
            random.shuffle(tracks["tracks"])
            
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
        await ctx.followup.send(embed=embed)

    @commands.slash_command(guild_ids=[TEST_GUILDID], description="Set loop")
    @option(
        "loop",
        description="loop",
        choices=["Off", "One", "Queue"],
        default="Off",
        required=True,
    )
    async def loop(self, ctx: ApplicationContext, loop: str):
        subscription = self.subscriptions.getQueue(ctx.guild_id)
        subscription.loop = loop
        await ctx.respond(
            embed=SuccessEmbed(self.bot, f"Current loop: **{subscription.loop}**")
        )
        
    @commands.slash_command(guild_ids=[TEST_GUILDID], description="Shuffle")
    async def shuffle(self, ctx: ApplicationContext):
        subscription = self.subscriptions.getQueue(ctx.guild_id)
        random.shuffle(subscription.queue)
        await ctx.respond(
            embed=SuccessEmbed(self.bot, f"Shuffle complete")
        )

    @commands.slash_command(guild_ids=[TEST_GUILDID], description="Skip to next song")
    async def skip(self, ctx: ApplicationContext):
        await ctx.defer()
        subscription = self.subscriptions.getQueue(ctx.guild_id)
        try:
            track = await subscription.skip()
            embed = SuccessEmbed(
                self.bot, f"Skipped to [**{track.title}**]({track.url})"
            )
            embed.set_thumbnail(url=track.thumbnail)
            await ctx.followup.send(embed=embed)
        except Empty:
            await ctx.followup.send(embed=SuccessEmbed(self.bot, f"No song left"))

    @commands.slash_command(
        guild_ids=[TEST_GUILDID], description="Leave current channel"
    )
    async def leave(self, ctx: ApplicationContext):
        subscription = self.subscriptions.getQueue(ctx.guild_id)
        await subscription.leave(message=False)
        await ctx.respond(embed=LeaveEmbed(self.bot))

    @play.before_invoke
    async def ensure_voice(self, ctx: ApplicationContext):
        if ctx.voice_client is None:
            if not ctx.author.voice:
                await ctx.respond(
                    embed=ErrorEmbed(
                        self.bot, "You are not connected to a voice channel."
                    )
                )
                raise commands.CommandError("Author not connected to a voice channel.")

    @loop.before_invoke
    @skip.before_invoke
    @leave.before_invoke
    async def ensure_subscription(self, ctx: ApplicationContext):
        subscription = self.subscriptions.getQueue(ctx.guild_id)
        if not subscription:
            await ctx.respond(
                embed=ErrorEmbed(self.bot, "You are not connected to a voice channel.")
            )
            raise commands.CommandError("Author not connected to a voice channel.")
