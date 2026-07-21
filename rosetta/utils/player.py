import logging
import random
from enum import Enum
from typing import Generic, TypeVar

from lava_lyra import NodePool, Player, Track

logger = logging.getLogger("rosetta")

T = TypeVar("T")


class LoopMode(Enum):
    NONE = None
    ONE = "one"
    QUEUE = "queue"


class Queue(Generic[T]):
    def __init__(self):
        self._queue: list[T] = []
        self._now_playing: T | None = None
        self.loop = LoopMode.NONE

    def __len__(self) -> int:
        return len(self._queue)

    def __iter__(self):
        return iter(self._queue)

    def __getitem__(self, index: int) -> T:
        return self._queue[index]

    @property
    def is_empty(self) -> bool:
        return len(self._queue) == 0

    @property
    def now_playing(self) -> T | None:
        """Return the currently playing item."""
        return self._now_playing

    def add(self, items: list[T]):
        """Add items to the end of the queue."""
        self._queue.extend(items)

    def add_front(self, items: list[T]):
        """Add items to the front of the queue."""
        self._queue = items + self._queue

    def get(self) -> T | None:
        """Remove and return the first item from the queue."""
        # Loop one: return the currently playing track
        if self.loop == LoopMode.ONE and self._now_playing is not None:
            return self._now_playing

        # Empty queue handling
        if self.is_empty:
            # Loop queue with nothing left: return now_playing
            if self.loop == LoopMode.QUEUE and self._now_playing is not None:
                return self._now_playing
            return None

        # Get next item
        item = self._queue.pop(0)
        if self.loop == LoopMode.QUEUE:
            self._queue.append(self._now_playing)

        self._now_playing = item
        return item

    def skip_to(self, index: int) -> T | None:
        """Skip to a specific index in the queue."""
        if self.is_empty:
            return None

        # Add current now_playing to end if loop queue
        if self.loop == LoopMode.QUEUE and self._now_playing is not None:
            self._queue.append(self._now_playing)

        # Skip through items up to index
        for _ in range(index):
            item = self._queue.pop(0)
            if self.loop == LoopMode.QUEUE:
                self._queue.append(item)

        # Get the target item
        item = self._queue.pop(0)
        self._now_playing = item
        return item

    def peek(self) -> T | None:
        """Return the first item without removing it."""
        if self.is_empty:
            return None
        return self._queue[0]

    def peek_n(self, n: int, _start: int = 0) -> list[T]:
        """Return the first n items without removing them."""
        return self._queue[_start:n]

    def remove(self, index: int) -> T | None:
        """Remove and return an item at the specified index."""
        if index < 0 or index >= len(self._queue):
            return None
        return self._queue.pop(index)

    def clear(self):
        """Clear all items from the queue."""
        self._queue.clear()
        self._now_playing = None

    def shuffle(self):
        """Shuffle the queue randomly."""
        random.shuffle(self._queue)

    def move(self, from_index: int, to_index: int) -> bool:
        """Move an item from one position to another."""
        if from_index < 0 or from_index >= len(self._queue):
            return False
        if to_index < 0 or to_index >= len(self._queue):
            return False
        item = self._queue.pop(from_index)
        self._queue.insert(to_index, item)
        return True

    def set_loop(self, mode: LoopMode = None) -> LoopMode:
        """Cycle through loop modes or set a specific mode."""
        if mode is not None:
            self.loop = mode
        else:
            if self.loop == LoopMode.NONE:
                self.loop = LoopMode.ONE
            elif self.loop == LoopMode.ONE:
                self.loop = LoopMode.QUEUE
            else:
                self.loop = LoopMode.NONE
        return self.loop


class CustomPlayer(Player):
    def __init__(
        self, client, channel, *, node=None, node_identifier: str | None = None
    ):
        if node_identifier is not None and node is None:
            node = NodePool.get_node(identifier=node_identifier)
        super().__init__(client, channel, node=node)
        self.queue = Queue[Track]()

    async def swap_node(self, new_node):
        """Handle swapping to a new node, pr is in pending"""
        data = None
        if self.current:
            data = {
                "position": self.position,
                "track": {"encoded": self.current.track_id},
                "volume": self._volume,
                "paused": self._paused,
                "filters": self.filters.get_all_payloads()
                if not self.filters.empty
                else None,
            }

        del self._node._players[self._guild.id]

        old_node = self._node
        self._node = new_node
        self._node._players[self._guild.id] = self

        await self._refresh_endpoint_uri(new_node._session_id)

        await self._dispatch_voice_update()

        if data:
            try:
                await self._node.send(
                    method="PATCH",
                    path=self._player_endpoint_uri,
                    guild_id=self._guild.id,
                    data=data,
                )
                if self._log:
                    self._log.info(
                        f"Successfully restored player state on new node {new_node._identifier}"
                    )
            except Exception as e:
                if self._log:
                    self._log.error(f"Failed to restore player state on new node: {e}")

        if self._log:
            self._log.info(
                f"Swapped player from node {old_node._identifier} to {new_node._identifier}"
            )
