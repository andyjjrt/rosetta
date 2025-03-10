import discord
from discord import Bot, option, ApplicationContext, OptionChoice
from discord.ext import commands
from utils.embeds import PingEmbed
import os, json, ffmpeg, io, asyncio
import subprocess
import re


class Mygo(commands.Cog):
    FOLDER = "../mygo-ave-video"
    data = []

    def __init__(self, bot: Bot):
        self.bot = bot
        with open(os.path.join(self.FOLDER, "data.json")) as f:
            Mygo.data = json.load(f)

    @staticmethod
    def get_text(self: discord.AutocompleteContext):
        text = self.options["text"]
        return [
            f"[{d['segment_id']}] {d['text']} ({d['episode']})"
            for d in Mygo.data
            if text in d["text"]
        ][:25]

    async def generate_gif(self, segment_data, resolution):
        def fps(s) -> float:
            fls = s.split("/")
            return float(fls[0]) / float(fls[1])

        filename = os.path.join(self.FOLDER, f"{segment_data['episode']}.mp4")

        probe_m = ffmpeg.probe(filename=filename)
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

        gif_buffer = io.BytesIO()

        # Store the output in a BytesIO buffer
        gif_buffer.write(stdout)
        gif_buffer.seek(0)

        return gif_buffer

    @commands.slash_command(
        name="mygo",
        integration_types=set(
            [
                discord.IntegrationType.user_install,
                discord.IntegrationType.guild_install,
            ]
        ),
    )
    @option(
        "text",
        type=discord.SlashCommandOptionType.string,
        autocomplete=get_text,
    )
    @option(
        "resolution", type=int, choices=[240, 360, 720], default=240, required=False
    )
    @option("ephemeral", type=bool, default=False, required=False)
    async def mygo(self, ctx: ApplicationContext, text: str, resolution: int, ephemeral: bool):
        await ctx.defer(ephemeral=ephemeral)
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
        await ctx.respond(file=file, ephemeral=ephemeral)
