import asyncio
import io
import json
import os
import re
import subprocess
from typing import List

import discord
import ffmpeg
from discord import app_commands
from discord.ext import commands

from ..utils.cog import Cog


class Mygo(Cog):
    FOLDER = "mygo-ave-video"
    data = []

    def __init__(self, bot: commands.Bot):
        super().__init__(bot=bot)
        with open(os.path.join(self.FOLDER, "data.json")) as f:
            Mygo.data = json.load(f)

    async def text_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        return [
            app_commands.Choice(
                name=f"[{d['segment_id']}] {d['text']} ({d['episode']})",
                value=f"[{d['segment_id']}] {d['text']}",
            )
            for d in Mygo.data
            if current in d["text"]
        ][:25]

    async def generate_gif(self, segment_data, resolution):
        def fps(s) -> float:
            fls = s.split("/")
            return float(fls[0]) / float(fls[1])

        filename = os.path.join(self.FOLDER, f"{segment_data['episode']}.mp4")

        try:
            probe_m = ffmpeg.probe(filename=filename)
        except ffmpeg.Error as e:
            stderr_output = (
                e.stderr.decode("utf-8", errors="replace")
                if e.stderr
                else "(no stderr)"
            )
            self._logger.error(f"ffprobe failed for '{filename}':\n{stderr_output}")
            raise commands.CommandError(
                f"ffprobe failed for `{filename}`: {stderr_output[:200]}"
            )

        seek: float = float(
            min(segment_data["frame_start"], segment_data["frame_end"])
        ) / fps(probe_m["streams"][0]["r_frame_rate"])
        delta = segment_data["frame_end"] - segment_data["frame_start"]

        palettegen = (
            ffmpeg.input(filename=filename, ss=seek)
            .trim(start_frame=0, end_frame=delta + 1)
            .filter(filter_name="scale", width=-1, height=resolution)
            .filter(filter_name="palettegen", stats_mode="diff")
        )
        scale = ffmpeg.input(filename=filename, ss=seek).filter(
            filter_name="scale", width=-1, height=resolution
        )
        # stream order needs to be scale -> palettegen
        cmd = (
            ffmpeg.filter(
                [scale, palettegen],
                filter_name="paletteuse",
                dither="floyd_steinberg",
                diff_mode="rectangle",
            )
            .output("pipe:", vframes=delta + 1, format="gif", vcodec="gif")
            .compile()
        )

        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            stderr_output = (
                stderr.decode("utf-8", errors="replace") if stderr else "(no stderr)"
            )
            self._logger.error(
                f"ffmpeg GIF generation failed for '{filename}' (exit {process.returncode}):\n{stderr_output}"
            )
            raise commands.CommandError(
                f"ffmpeg failed (exit {process.returncode}): {stderr_output[:200]}"
            )

        gif_buffer = io.BytesIO()

        # Store the output in a BytesIO buffer
        gif_buffer.write(stdout)
        gif_buffer.seek(0)

        return gif_buffer

    @app_commands.command(name="mygo", description="Generate MyGO GIF from anime")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        text="Select a scene",
        resolution="Output resolution",
        ephemeral="Hide response",
    )
    @app_commands.autocomplete(text=text_autocomplete)
    @app_commands.choices(
        resolution=[
            app_commands.Choice(name="240p", value=240),
            app_commands.Choice(name="360p", value=360),
            app_commands.Choice(name="720p", value=720),
        ]
    )
    async def mygo(
        self,
        interaction: discord.Interaction,
        text: str,
        resolution: int = 240,
        ephemeral: bool = False,
    ):
        await interaction.response.defer(ephemeral=ephemeral)
        match = re.match(r"\[([^\]]+)\] (.+)", text)
        if match:
            segment_id = match.group(1)
        else:
            raise commands.CommandError("Wrong format")
        result = [d for d in self.data if str(d["segment_id"]) == segment_id]
        assert len(result) == 1
        result = result[0]
        gif_buffer = await self.generate_gif(result, resolution)

        # Send the GIF
        file = discord.File(gif_buffer, filename=f"{result['text']}.gif")
        await interaction.followup.send(file=file, ephemeral=ephemeral)
