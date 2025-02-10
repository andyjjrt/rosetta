import discord
from discord import VoiceClient, Bot
from discord.channel import TextChannel
from queue import SimpleQueue, Empty
from data.track import Track
from utils.embeds import LeaveEmbed
import asyncio


class Queue:
    def __init__(
        self,
        bot: Bot,
        guildId: str,
        voiceClient: VoiceClient,
        messageChannel: TextChannel,
        callbackFn,
        tracks: list[Track],
        loop: str = "Off",
    ) -> None:
        self.bot = bot
        self.guildId = guildId
        self.queue = tracks

        self.nowPlaying: Track | None = None
        self.checkLock = False

        self.loop = loop
        self.voiceClient = voiceClient
        self.messageChannel = messageChannel

        self.task = asyncio.get_event_loop().create_task(self._startSession())
        self.task.add_done_callback(callbackFn)

    def addTracks(self, tracks: list[Track]):
        for track in tracks:
            self.queue.append(track)
        
    async def skip(self):
        self.voiceClient.stop()
        self.checkLock = True
        await self._process()
        self.checkLock = False
        return self.nowPlaying

    async def leave(self, message=True):
        if message:
            await self.messageChannel.send(embed=LeaveEmbed(self.bot))
        await self.voiceClient.disconnect()
        self.task.cancel()

    async def _process(self):
        if len(self.queue) == 0:
            if self.loop == "Off":
                self.checkLock = False
                raise Empty
        else:
            if self.loop != "One" or not self.nowPlaying:
                if self.loop == "Queue":
                    self.queue.append(self.nowPlaying)
                track = self.queue.pop(0)
                self.nowPlaying = track

            player = await self.nowPlaying.createAudio()
            self.voiceClient.play(
                player, after=lambda e: print(f"Player error: {e}") if e else None
            )

    async def _startSession(self):
        while True:
            if not self.voiceClient.is_playing() and not self.checkLock:
                try:
                    await self._process()
                except Empty:
                    await self.leave()
                    return
            await asyncio.sleep(1)

class Assistant:
    def __init__(
        self,
        bot: Bot,
        guildId: str,
        voiceClient: VoiceClient,
        messageChannel: TextChannel,
    ) -> None:
        self.bot = bot
        self.guildId = guildId
        self.voiceClient = voiceClient
        self.messageChannel = messageChannel
        
    def start(self):
        self.voiceClient.start_recording(
            discord.sinks.WaveSink(),
            self._done,
            self.messageChannel
        )
        
    async def stop(self):
        self.voiceClient.stop_recording()
        await self.voiceClient.disconnect()
            
    async def _done(self, sink: discord.sinks, channel: discord.TextChannel, *args):
        recorded_users = [
            f"<@{user_id}>"
            for user_id, audio in sink.audio_data.items()
        ]
        files = [discord.File(audio.file, f"{user_id}.{sink.encoding}") for user_id, audio in sink.audio_data.items()]  # List down the files.
        for user_id, audio in sink.audio_data.items():
            with open(f"{user_id}.{sink.encoding}", "wb") as f:
                f.write(audio.file.getbuffer())
        await channel.send(f"finished recording audio for: {', '.join(recorded_users)}.", files=files)

class Subscription:

    _serverStatus = dict()

    def __init__(self) -> None:
        pass

    def createQueue(
        self,
        bot: Bot,
        guildId: str,
        channel: TextChannel,
        voiceClient: VoiceClient,
        tracks: list[Track],
        loop: str,
    ):
        if guildId in self._serverStatus:
            raise Exception("Guild already have subscription")
        self._serverStatus[guildId] = Queue(
            bot,
            guildId,
            voiceClient,
            channel,
            lambda x: self.remove(guildId),
            tracks,
            loop,
        )
        print(self._serverStatus)
        
    def createAssistant(
        self,
        bot: Bot,
        guildId: str,
        channel: TextChannel,
        voiceClient: VoiceClient,
    ):
        if guildId in self._serverStatus:
            raise Exception("Guild already have subscription")
        self._serverStatus[guildId] = Assistant(
            bot,
            guildId,
            voiceClient,
            channel,
        )
        self._serverStatus[guildId].start()

    def remove(self, guildId: str):
        if not guildId in self._serverStatus:
            raise Exception("guild don't have any queue")
        del self._serverStatus[guildId]

    def get(self, guildId: str) -> Queue | Assistant | None:
        return self._serverStatus.get(guildId)
