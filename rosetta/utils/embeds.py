import configparser
from datetime import datetime
from typing import List

from discord import Colour, Embed, User
from openai.types.completion_usage import CompletionUsage

from .track import Track

config = configparser.ConfigParser()
config.read("config.ini")


def PingEmbed(user: User, latency: float):
    embed = Embed(
        title=":ping_pong:  Pong",
        description=f"Ball flew back in {int(latency * 1000)}ms",
        colour=Colour.teal(),
        timestamp=datetime.now(),
    )
    embed.set_footer(text=user.name, icon_url=user.avatar)
    return embed


def SuccessEmbed(user: User, message: str):
    embed = Embed(
        title=f"{config['bot.emoji']['success']} Success",
        description=message,
        colour=Colour.green(),
        timestamp=datetime.now(),
    )
    embed.set_footer(text=user.name, icon_url=user.avatar)
    return embed


def ErrorEmbed(user: User, error: str):
    embed = Embed(
        title=f"{config['bot.emoji']['error']} Error",
        description=error,
        colour=Colour.red(),
        timestamp=datetime.now(),
    )
    embed.set_footer(text=user.name, icon_url=user.avatar)
    return embed


def InfoEmbed(user: User, message: str):
    embed = Embed(
        title=":information_source:   Info",
        description=message,
        colour=Colour.blurple(),
        timestamp=datetime.now(),
    )
    embed.set_footer(text=user.name, icon_url=user.avatar)
    return embed


def NowPlayingEmbed(track: Track, queue: List[Track]):
    embed = Embed(
        title=f"{config['bot.emoji']['youtube']} Now Playing",
        description=f"[**{track.title}**]({track.url})\n\n`{track.time[0]}`{track.progress}`{track.time[1]}`\n",
        colour=Colour.green(),
        timestamp=datetime.now(),
    )
    embed.set_thumbnail(url=track.thumbnail)
    if len(queue) > 0:
        embed.add_field(
            name=f"💭 Next ({len(queue)} left)",
            value=f"{'\n'.join([f'- [{t.title}]({t.url}) `{t.time[1]}`' for t in queue[:3]])}",
            inline=False
        )
    embed.set_footer(text=track.author.name, icon_url=track.author.avatar)
    return embed


def LeaveEmbed(user: User):
    embed = Embed(
        title=":wave:  Leaving",
        description="Bye~",
        colour=Colour.teal(),
        timestamp=datetime.now(),
    )
    embed.set_footer(text=user.name, icon_url=user.avatar)
    return embed


def SearchEmbed(user: User, keyword: str, tracks: List[Track]):
    embed = Embed(
        title=f':mag: Search result of **"{keyword}"**',
        description="\n".join(
            [
                f"{i + 1}. [**{track.title}**]({track.url})"
                for i, track in enumerate(tracks)
            ]
        ),
        colour=Colour.teal(),
        timestamp=datetime.now(),
    )
    embed.set_footer(text=user.name, icon_url=user.avatar)
    return embed


def ProcessingEmbed(user: User, message: str = "Processing..."):
    return Embed(
        title=":globe_with_meridians:   Processing",
        description=message,
        colour=Colour.blurple(),
    )


def LLMPerformanceEmbed(model: str, ttft: float, tps: float, usage: CompletionUsage):
    embed = Embed(
        title=":bar_chart:  LLM Performance",
        colour=Colour.dark_blue(),
        timestamp=datetime.now(),
    )

    embed.add_field(name="Model", value=model, inline=False)
    embed.add_field(name="TTFT", value=ttft, inline=False)
    embed.add_field(name="TPS", value=tps, inline=False)
    embed.add_field(name="Input Tokens", value=usage.prompt_tokens, inline=False)
    embed.add_field(name="Output Tokens", value=usage.completion_tokens, inline=False)

    return embed
