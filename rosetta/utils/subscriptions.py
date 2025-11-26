import asyncio
import logging
from queue import Empty

from discord import VoiceClient
from discord.channel import TextChannel
from discord.ext import commands

from .embeds import LeaveEmbed
from .track import Track


class Queue:
    def __init__(
        self,
        bot: commands.Bot,
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
        self.logger = logging.getLogger("rosetta")

        self.nowPlaying: Track | None = None
        self.checkLock = False

        self.loop = loop
        self.voiceClient = voiceClient
        self.messageChannel = messageChannel

        self.task = asyncio.get_event_loop().create_task(self._startSession())
        self.task.add_done_callback(callbackFn)

    def addTracks(self, tracks: list[Track], top: bool = False):
        if top:
            self.queue = tracks + self.queue
        else:
            self.queue += tracks

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
        if self.loop == "Off" and len(self.queue) == 0:
            self.checkLock = False
            raise Empty
        if self.loop != "One" or not self.nowPlaying:
            if self.loop == "Queue":
                self.queue.append(self.nowPlaying)
            track = self.queue.pop(0)
            self.nowPlaying = track
        try:
            player = await self.nowPlaying.createAudio()
            self.voiceClient.play(
                player,
                after=lambda e: self.logger.error(f"Player error: {e}") if e else None,
            )
        except Exception as e:
            logging.error(e)
            self.voiceClient.stop()
            await self._process()
        self.checkLock = False

    async def _startSession(self):
        while True:
            if not self.voiceClient.is_playing() and not self.checkLock:
                try:
                    self.checkLock = True
                    await self._process()
                except Empty:
                    await self.leave()
            await asyncio.sleep(1)


class Subscription:
    _serverStatus = dict()

    def __init__(self) -> None:
        pass

    def createQueue(
        self,
        bot: commands.Bot,
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

    def remove(self, guildId: str):
        if guildId not in self._serverStatus:
            raise Exception("guild don't have any queue")
        del self._serverStatus[guildId]

    def get(self, guildId: str) -> Queue | None:
        return self._serverStatus.get(guildId)
