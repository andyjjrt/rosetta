from discord import FFmpegPCMAudio, Member, User
import asyncio, os
import yt_dlp

ytdl_format_options = {
    "format": "ba[ext=m4a]",
    "outtmpl": "music/%(id)s.%(ext)s",
    "extractor_retries": 1,
    "quiet": True,
    "ignoreerrors": True,
    "extract_flat": True
}

class Track:
    def __init__(self, data: dict, user: Member | User):
        self.data = data
        self.title = data.get("title")
        self.thumbnail = data["thumbnails"][0]["url"]
        self.url = data.get("original_url") if data.get("original_url") else data.get("url")
        self.channel = data.get("channel")
        self.channel_url = data.get("channel_url")
        self.ytId = data.get("id")
        self.author = user
    
    def __str__(self) -> str:
        return f"Track(title=\"{self.title}\", channel=\"{self.channel}\")"

    async def createAudio(self):
        with yt_dlp.YoutubeDL(ytdl_format_options) as ytdl:
            filename = f"music/{self.ytId}.m4a"
            if not os.path.exists(filename):
                await asyncio.get_event_loop().run_in_executor(None, lambda: ytdl.extract_info(self.url))
            return FFmpegPCMAudio(filename)

    @classmethod
    async def from_url(cls, url: str, user: Member | User, *, loop=None):
        with yt_dlp.YoutubeDL(ytdl_format_options) as ytdl:
            loop = loop or asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(url, download=False)
            )
            title = data.get("title")
            url = data.get("original_url")
            thumbnail = data["thumbnails"][0]["url"]
            if "entries" in data:
                data = data["entries"]
            else:
                data = [data]
            tracks = [cls(d, user) for d in data]
            return {
                "title": title,
                "url": url,
                "thumbnail": thumbnail,
                "tracks": tracks
            }