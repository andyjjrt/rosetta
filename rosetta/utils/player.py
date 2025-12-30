import random
from enum import Enum
from typing import Generic, TypeVar

from pomice import Player, Track

T = TypeVar("T")


class LoopMode(Enum):
    NONE = None
    ONE = "one"
    QUEUE = "queue"


class Queue(Generic[T]):
    def __init__(self):
        self._queue: list[T] = []
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

    def add(self, items: list[T]):
        """Add items to the end of the queue."""
        self._queue.extend(items)

    def add_front(self, items: list[T]):
        """Add items to the front of the queue."""
        self._queue = items + self._queue

    def get(self) -> T | None:
        """Remove and return the first item from the queue."""
        if self.is_empty:
            return None
        if self.loop == LoopMode.ONE:
            return self._queue[0]
        item = self._queue.pop(0)
        if self.loop == LoopMode.QUEUE:
            self._queue.append(item)
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
    def __init__(self, client, channel, *, node=None):
        super().__init__(client, channel, node=node)
        self.queue = Queue[Track]()
    
    async def swap_node(self, new_node):
        return await super()._swap_node(new_node=new_node)
