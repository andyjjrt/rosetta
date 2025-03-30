from typing import List
from discord import Embed, EmbedField, EmbedFooter, Colour, User
from datetime import datetime
from utils.track import Track
import configparser
from pydantic_ai.agent import AgentRunResult

config = configparser.ConfigParser()
config.read("config.ini")


def PingEmbed(user: User, latency: float):
    return Embed(
        title=":ping_pong:  Pong",
        description=f"Ball flew back in {int(latency * 1000)}ms",
        colour=Colour.teal(),
        footer=EmbedFooter(text=user.name, icon_url=user.avatar),
        timestamp=datetime.now(),
    )


def SuccessEmbed(user: User, message: str):
    return Embed(
        title=f"{config['bot.emoji']['success']} Success",
        description=message,
        colour=Colour.green(),
        footer=EmbedFooter(text=user.name, icon_url=user.avatar),
        timestamp=datetime.now(),
    )


def ErrorEmbed(user: User, error: str):
    return Embed(
        title=f"{config['bot.emoji']['error']} Error",
        description=error,
        colour=Colour.red(),
        footer=EmbedFooter(text=user.name, icon_url=user.avatar),
        timestamp=datetime.now(),
    )


def InfoEmbed(user: User, message: str):
    return Embed(
        title=":information_source:   Info",
        description=message,
        colour=Colour.blurple(),
        footer=EmbedFooter(text=user.name, icon_url=user.avatar),
        timestamp=datetime.now(),
    )


def NowPlayingEmbed(track: Track, queue: List[Track]):
    queueMessage = None
    if len(queue) > 0:
        queueMessage = [
            EmbedField(
                name=f"💭 Next ({len(queue)} left)",
                value=f"{'\n'.join([f'- [{t.title}]({t.url}) `{t.time[1]}`' for t in queue[:3]])}",
            )
        ]
    return Embed(
        title=f"{config['bot.emoji']['youtube']} Now Playing",
        description=f"[**{track.title}**]({track.url})\n\n`{track.time[0]}`{track.progress}`{track.time[1]}`\n",
        thumbnail=track.thumbnail,
        fields=queueMessage,
        colour=Colour.green(),
        footer=EmbedFooter(text=track.author.name, icon_url=track.author.avatar),
        timestamp=datetime.now(),
    )


def LeaveEmbed(user: User):
    return Embed(
        title=":wave:  Leaving",
        description="Bye~",
        colour=Colour.teal(),
        footer=EmbedFooter(text=user.name, icon_url=user.avatar),
        timestamp=datetime.now(),
    )


def SearchEmbed(user: User, keyword: str, tracks: List[Track]):
    return Embed(
        title=f':mag: Search result of **"{keyword}"**',
        description="\n".join(
            [
                f"{i + 1}. [**{track.title}**]({track.url})"
                for i, track in enumerate(tracks)
            ]
        ),
        colour=Colour.teal(),
        footer=EmbedFooter(text=user.name, icon_url=user.avatar),
        timestamp=datetime.now(),
    )


def ProcessingEmbed(user: User, message: str = "Processing..."):
    return Embed(
        title=":globe_with_meridians:   Processing",
        description=message,
        colour=Colour.blurple(),
    )


def OllamaEmbed(text: str, result: AgentRunResult[str]):
    usage = result
    print(usage)
    embed = Embed(
        title=":llama: Ollama response",
        colour=Colour.dark_blue(),
        footer=EmbedFooter(text=f"test"),
        timestamp=datetime.now(),
    )

    embed.add_field(name="Input", value=text, inline=False)
    embed.add_field(name="Output", value=result.data, inline=False)

    return embed
