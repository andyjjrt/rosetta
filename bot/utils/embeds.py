from typing import List
from discord import Embed, EmbedFooter, Colour, User
from datetime import datetime
from utils.track import Track


def PingEmbed(user: User, latency: float):
    return Embed(
        title=":ping_pong:  Pong",
        description=f"Ball flew back in {int(latency*1000)}ms",
        colour=Colour.teal(),
        footer=EmbedFooter(text=user.name, icon_url=user.avatar),
        timestamp=datetime.now(),
    )
    
def SuccessEmbed(user: User, message: str):
    return Embed(
        title=":white_check_mark:  Success",
        description=message,
        colour=Colour.green(),
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

def ErrorEmbed(user: User, error: str):
    return Embed(
        title=":x:  Error",
        description=error,
        colour=Colour.red(),
        footer=EmbedFooter(text=user.name, icon_url=user.avatar),
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
        title=f":mag: Search result of **\"{keyword}\"**",
        description="\n".join([f"{i + 1}. [**{track.title}**]({track.url})" for i, track in enumerate(tracks)]),
        colour=Colour.teal(),
        footer=EmbedFooter(text=user.name, icon_url=user.avatar),
        timestamp=datetime.now(),
    )
    
def ProcessingEmbed(user: User, message: str = "Processing..."):
    return Embed(
        title=":globe_with_meridians:   Processing",
        description=message,
        colour=Colour.blurple(),
        footer=EmbedFooter(text=user.name, icon_url=user.avatar),
        timestamp=datetime.now(),
    )