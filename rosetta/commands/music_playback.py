from dataclasses import dataclass
from functools import partial

import discord
from discord.ext import commands

from rosetta.models.music import MusicErrorCode, MusicFailure, PlayRequest, PlaySuccess
from rosetta.utils.embeds import SuccessEmbed
from rosetta.utils.music_service import MusicService
from rosetta.utils.nodepool import HybridNodePool
from rosetta.utils.player import CustomPlayer


async def ensure_voice_connection(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client if interaction.guild else None
    adapter = interaction.extras.get("logger")
    if voice_client is None:
        if not interaction.user.voice:
            adapter.warning(
                f"User {interaction.user} not in voice channel in guild {interaction.guild.name}"
            )
            raise commands.CommandError("You are not connected to a voice channel.")
    return voice_client


async def ensure_active_player(interaction: discord.Interaction) -> CustomPlayer:
    player = interaction.guild.voice_client if interaction.guild else None
    adapter = interaction.extras.get("logger")
    if not player:
        adapter.warning(f"Player not found for guild {interaction.guild.name}")
        raise commands.CommandError("The bot is not playing")
    return player


@dataclass(frozen=True, slots=True)
class DiscordPlayRequest:
    interaction: discord.Interaction
    url: str
    loop: str = "Off"
    shuffle: bool = False
    top: bool = False
    node_name: str | None = None


async def play_from_interaction(
    pool: HybridNodePool,
    service: MusicService,
    request: DiscordPlayRequest,
) -> discord.Embed:
    interaction = request.interaction
    adapter = interaction.extras.get("logger")
    player: CustomPlayer | None = (
        interaction.guild.voice_client if interaction.guild else None
    )
    if player is None:
        if interaction.user.voice and interaction.user.voice.channel:
            await pool.destroy_guild_players(interaction.user.voice.channel.guild.id)
            player_cls = (
                partial(CustomPlayer, node_identifier=request.node_name)
                if request.node_name
                else CustomPlayer
            )
            player = await interaction.user.voice.channel.connect(cls=player_cls)

    result = await service.enqueue(
        player,
        PlayRequest(
            user_id=str(interaction.user.id),
            chat_channel_id=str(interaction.channel.id),
            url=request.url,
            loop=request.loop,
            shuffle=request.shuffle,
            top=request.top,
            node_name=request.node_name,
        ),
    )
    match result:
        case MusicFailure(code=MusicErrorCode.NO_TRACKS_FOUND):
            adapter.error(f"No results found for search term: {request.url}")
            raise commands.CommandError("No results were found for that search term.")
        case MusicFailure(message=message):
            adapter.error(message)
            raise commands.CommandError(message)
        case PlaySuccess(
            title=name,
            uri=uri,
            thumbnail=thumbnail,
            enqueued_count=enqueued_count,
            node_name=result_node_name,
        ):
            if enqueued_count > 1:
                adapter.info(f"Enqueued playlist: {name} ({enqueued_count} tracks)")
            else:
                adapter.info(f"Enqueued track: {name}")

    embed = SuccessEmbed(interaction.user, f"Enqueued [**{name}**]({uri})")
    embed.set_footer(
        text=f"{interaction.user.name} • {result_node_name}",
        icon_url=interaction.user.avatar,
    )
    embed.set_thumbnail(url=thumbnail)
    return embed
