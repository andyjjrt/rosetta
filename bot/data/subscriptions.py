from discord import VoiceClient, Bot
from discord.channel import TextChannel
from queue import SimpleQueue, Empty
from data.track import Track
from utils.embeds import LeaveEmbed
import asyncio


class Subscription:
    def __init__(
        self,
        bot: Bot,
        guildId: str,
        voiceChannel: VoiceClient,
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
        self.voiceChannel = voiceChannel
        self.messageChannel = messageChannel
        self.task = asyncio.get_event_loop().create_task(self._startSession())
        self.task.add_done_callback(callbackFn)

    def addTracks(self, tracks: list[Track]):
        for track in tracks:
            self.queue.put(track)

    async def skip(self):
        self.voiceChannel.stop()
        self.checkLock = True
        await self._process()
        self.checkLock = False
        return self.nowPlaying

    async def leave(self, message = True):
        if message:
            await self.messageChannel.send(embed=LeaveEmbed(self.bot))
        await self.voiceChannel.channel.set_status("")
        await self.voiceChannel.disconnect()
        self.task.cancel()
    
    async def _process(self):
        if len(self.queue) == 0 and self.loop == "Off":
            self.checkLock = False
            raise Empty

        if self.loop != "One" or not self.nowPlaying:
            if self.loop == "Queue":
                self.queue.append(self.nowPlaying)
            track = self.queue.pop(0)
            self.nowPlaying = track

        player = await self.nowPlaying.createAudio()
        await self.voiceChannel.channel.set_status(
            f":musical_note: {self.nowPlaying.title}"
        )
        self.voiceChannel.play(
            player, after=lambda e: print(f"Player error: {e}") if e else None
        )

    async def _startSession(self):
        while True:
            if not self.voiceChannel.is_playing() and not self.checkLock:
                try:
                    await self._process()
                except Empty:
                    await self.leave()
                    return
            await asyncio.sleep(1)


class ServerQueue:

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
            raise Exception("guild already have queue")
        self._serverStatus[guildId] = Subscription(
            bot,
            guildId,
            voiceClient,
            channel,
            lambda event: self.removeQueue(guildId),
            tracks,
            loop,
        )
        print(self._serverStatus)

    def removeQueue(self, guildId: str):
        if not guildId in self._serverStatus:
            raise Exception("guild don't have any queue")
        del self._serverStatus[guildId]
        print(self._serverStatus)

    def getQueue(self, guildId: str) -> Subscription | None:
        return self._serverStatus.get(guildId)
