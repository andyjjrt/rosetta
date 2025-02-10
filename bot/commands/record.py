from enum import Enum
from discord import Bot, ApplicationContext
from discord.ext import commands
import discord
from utils.embeds import PingEmbed
from data.subscriptions import Subscription, Assistant
import os


class Record(commands.Cog):

    subscriptions = Subscription()
    
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.slash_command(description="Start Recording")
    async def start(self, ctx: discord.ApplicationContext):
        if ctx.voice_client is None:
            await ctx.author.voice.channel.connect()
        self.subscriptions.createAssistant(
            self.bot,
            ctx.guild_id,
            ctx.channel,
            ctx.voice_client,
        )

        await ctx.respond("The recording has started!")
    
    
    @commands.slash_command(description="Stop recording")
    async def stop(self, ctx: discord.ApplicationContext):
        subscription = self.subscriptions.get(ctx.guild_id)
        await subscription.stop()
        self.subscriptions.remove(ctx.guild_id)
        await ctx.delete()

    @start.before_invoke
    async def ensure_voice(self, ctx: ApplicationContext):
        if ctx.voice_client is None:
            if not ctx.author.voice:
                raise commands.CommandError("You are not connected to a voice channel.")
    
    @stop.before_invoke
    async def ensure_subscription(self, ctx: ApplicationContext):
        subscription = self.subscriptions.get(ctx.guild_id)
        if not subscription:
            raise commands.CommandError("You are not connected to a voice channel.")
        elif not type(subscription) == Assistant:
            raise commands.CommandError("You are not using assistant feature.")