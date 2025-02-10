from typing import List
from discord import Embed, EmbedFooter, Colour, Bot
from datetime import datetime
from data.track import Track


def PingEmbed(bot: Bot, latency: float):
    return Embed(
        title=":ping_pong:  Pong",
        description=f"Ball flew back in {int(latency*1000)}ms",
        colour=Colour.teal(),
        footer=EmbedFooter(text=bot.user.name, icon_url=bot.user.avatar),
        timestamp=datetime.now(),
    )
    
def SuccessEmbed(bot: Bot, message: str):
    return Embed(
        title=":white_check_mark:  Success",
        description=message,
        colour=Colour.green(),
        footer=EmbedFooter(text=bot.user.name, icon_url=bot.user.avatar),
        timestamp=datetime.now(),
    )

def ErrorEmbed(bot: Bot, error: str):
    return Embed(
        title=":x:  Error",
        description=error,
        colour=Colour.red(),
        footer=EmbedFooter(text=bot.user.name, icon_url=bot.user.avatar),
        timestamp=datetime.now(),
    )

def LeaveEmbed(bot: Bot):
    return Embed(
        title=":wave:  Leaving",
        description="Bye~",
        colour=Colour.teal(),
        footer=EmbedFooter(text=bot.user.name, icon_url=bot.user.avatar),
        timestamp=datetime.now(),
    )

def SearchEmbed(bot: Bot, keyword: str, tracks: List[Track]):
    return Embed(
        title=f":mag: Search result of **\"{keyword}\"**",
        description="\n".join([f"{i + 1}. [**{track.title}**]({track.url})" for i, track in enumerate(tracks)]),
        colour=Colour.teal(),
        footer=EmbedFooter(text=bot.user.name, icon_url=bot.user.avatar),
        timestamp=datetime.now(),
    )