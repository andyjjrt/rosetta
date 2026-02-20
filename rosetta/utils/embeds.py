import math
from datetime import datetime
from typing import List

import lava_lyra
from discord import Colour, Embed, User
from openai.types.completion_usage import CompletionUsage

from .config import EmojiConfig
from .player import CustomPlayer


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
        title=f"{EmojiConfig.get('success')} Success",
        description=message,
        colour=Colour.green(),
        timestamp=datetime.now(),
    )
    embed.set_footer(text=user.name, icon_url=user.avatar)
    return embed


def ErrorEmbed(user: User, error: str):
    embed = Embed(
        title=f"{EmojiConfig.get('error')} Error",
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


def _format_time(milliseconds: int) -> str:
    seconds = int(milliseconds / 1000)
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def _get_time_display(position_ms: int, duration_ms: int) -> tuple[str, str]:
    """Convert milliseconds to formatted time strings (mm:ss)"""
    currentMinute = int(position_ms / 60000)
    currentSecond = int(position_ms / 1000) % 60
    durationMinute = int(duration_ms / 60000)
    durationSecond = int(duration_ms / 1000) % 60

    times = (currentMinute, currentSecond, durationMinute, durationSecond)
    timesWithZeros = [f"0{t}" if t < 10 else t for t in times]

    return (
        f"{timesWithZeros[0]}:{timesWithZeros[1]}",
        f"{timesWithZeros[2]}:{timesWithZeros[3]}",
    )


def _get_progress_bar(position_ms: int, duration_ms: int) -> str:
    """Generate a progress bar based on current position and duration"""
    if duration_ms == 0:
        return ""

    progress = math.floor(position_ms * 10 / duration_ms)

    # [========]
    if progress == 0:
        return (
            EmojiConfig.get("progress_start_0")
            + EmojiConfig.get("progress") * 8
            + EmojiConfig.get("progress_end")
        )
    elif progress == 1:
        return (
            EmojiConfig.get("progress_start")
            + EmojiConfig.get("progress_mix")
            + EmojiConfig.get("progress") * 7
            + EmojiConfig.get("progress_end")
        )
    elif progress >= 10:
        return (
            EmojiConfig.get("progress_start")
            + EmojiConfig.get("progress_fill") * 8
            + EmojiConfig.get("progress_fill_end")
        )
    else:
        return (
            EmojiConfig.get("progress_start")
            + EmojiConfig.get("progress_fill") * (progress - 1)
            + EmojiConfig.get("progress_mix")
            + EmojiConfig.get("progress") * (8 - progress)
            + EmojiConfig.get("progress_end")
        )


def NowPlayingEmbed(player: CustomPlayer, current_page: int, page_size: int):
    track = player.current
    queue = player.queue

    current_time, duration_time = _get_time_display(player.position, track.length)
    progress_bar = _get_progress_bar(player.position, track.length)

    embed = Embed(
        title=f"{EmojiConfig.get('youtube')} Now Playing",
        description=f"[**{track.title}**]({track.uri})\n\n`{current_time}` {progress_bar} `{duration_time}`\n",
        colour=Colour.green(),
        timestamp=datetime.now(),
    )
    embed.set_thumbnail(url=track.thumbnail)

    start_idx = (current_page - 1) * page_size
    end_idx = min(start_idx + page_size, len(queue))
    if not queue.is_empty:
        embed.add_field(
            name=f"💭 Next ({len(queue)} left)",
            value=f"{'\n'.join([f'- [{t.title}]({t.uri}) `{_format_time(t.length)}`' for t in queue.peek_n(end_idx, _start=start_idx)])}",
            inline=False,
        )
    # embed.set_footer(text=track.requester.name, icon_url=track.requester.avatar)
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


def SearchEmbed(
    user: User, keyword: str, tracks: List[lava_lyra.Track] | lava_lyra.Playlist
):
    if isinstance(tracks, lava_lyra.Playlist):
        tracks = tracks.tracks
    embed = Embed(
        title=f':mag: Search result of **"{keyword}"**',
        description="\n".join(
            [
                f"{i + 1}. [**{track.title}**]({track.uri})"
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
