import asyncio
import math
import os

import ffmpeg
import yt_dlp
from discord import FFmpegOpusAudio, Member, User

from .config import EMOJI

ytdl_format_options = {
    "format": "ba[ext=m4a]",
    "outtmpl": "music/%(id)s.%(ext)s",
    "extractor_retries": 1,
    "quiet": True,
    "extract_flat": True,
}


class ReadableFFmpegOpusAudio(FFmpegOpusAudio):
    def __init__(
        self,
        source,
        *,
        bitrate=128,
        codec=None,
        executable="ffmpeg",
        pipe=False,
        stderr=None,
        before_options=None,
        options=None,
    ):
        super().__init__(
            source,
            bitrate=bitrate,
            codec=codec,
            executable=executable,
            pipe=pipe,
            stderr=stderr,
            before_options=before_options,
            options=options,
        )
        self.time = 0

    def read(self):
        self.time += 20
        return super().read()


class Track:
    def __init__(self, data: dict, user: Member | User):
        self.data = data
        self.title = data.get("title")
        self.thumbnail = data["thumbnails"][0]["url"]
        self.url = (
            data.get("original_url") if data.get("original_url") else data.get("url")
        )
        self.duration = data.get("duration") or 0
        self.channel = data.get("channel")
        self.channel_url = data.get("channel_url")
        self.ytId = data.get("id")
        self.author = user

        self.audio = None

    def __str__(self) -> str:
        return f'Track(title="{self.title}", channel="{self.channel}", duration="{self.duration}")'

    def _meanSound(self, filename: str):
        _, probe = (
            ffmpeg.input(filename)
            .output("pipe:", format="null", af="volumedetect")
            .run(capture_stdout=True, capture_stderr=True)
        )
        mean_volume = None
        for line in probe.decode().split("\n"):
            if "mean_volume" in line:
                mean_volume = float(line.split(":")[-1].strip().split()[0][:-2])
                break
        if mean_volume is None:
            raise Exception("Can't normalize sound")
        return mean_volume

    async def createAudio(self):
        with yt_dlp.YoutubeDL(ytdl_format_options) as ytdl:
            filename = os.path.join("music", f"{self.ytId}.m4a")
            if not os.path.exists(filename):
                errorCode = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ytdl.download([self.url])
                )
                if errorCode:
                    raise Exception(errorCode)
            meanVolume = self._meanSound(filename)
            self.audio = ReadableFFmpegOpusAudio(
                filename, options=f'-af "volume={-30 - meanVolume}dB"'
            )
            return self.audio

    @property
    def time(self):
        currentMinute = int(self.audio.time / 60000) if self.audio else 0
        currentSecond = int(self.audio.time / 1000) % 60 if self.audio else 0
        durationMinute = int(self.duration / 60)
        durationSecond = int(self.duration % 60)
        times = (currentMinute, currentSecond, durationMinute, durationSecond)
        timesWithZeros = [f"0{t}" if t < 10 else t for t in times]
        return (
            f"{timesWithZeros[0]}:{timesWithZeros[1]}",
            f"{timesWithZeros[2]}:{timesWithZeros[3]}",
        )

    @property
    def progress(self):
        if not self.audio:
            return ""
        progress = math.floor(self.audio.time / (self.duration * 100))
        # [========]
        if progress == 0:
            return (
                EMOJI.get("progress_start_0")
                + EMOJI.get("progress") * 8
                + EMOJI.get("progress_end")
            )
        elif progress == 1:
            return (
                EMOJI.get("progress_start")
                + EMOJI.get("progress_mix")
                + EMOJI.get("progress") * 7
                + EMOJI.get("progress_end")
            )
        elif progress >= 10:
            return (
                EMOJI.get("progress_start")
                + EMOJI.get("progress_fill") * 8
                + EMOJI.get("progress_fill_end")
            )
        else:
            return (
                EMOJI.get("progress_start")
                + EMOJI.get("progress_fill") * (progress - 1)
                + EMOJI.get("progress_mix")
                + EMOJI.get("progress") * (8 - progress)
                + EMOJI.get("progress_end")
            )

    @classmethod
    async def from_url(cls, url: str, user: Member | User, *, loop=None):
        with yt_dlp.YoutubeDL(ytdl_format_options) as ytdl:
            loop = loop or asyncio.get_running_loop()
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(url, download=False)
            )
            if data.get("_type") == "url":
                data = await loop.run_in_executor(
                    None, lambda: ytdl.extract_info(data.get("url"), download=False)
                )
            title = data.get("title")
            url = data.get("original_url")
            thumbnail = data.get("thumbnails")[0]["url"]
            if "entries" in data:
                data = data["entries"]
            else:
                data = [data]
            tracks = [cls(d, user) for d in data]
            return {
                "title": title,
                "url": url,
                "thumbnail": thumbnail,
                "tracks": tracks,
            }
