from lava_lyra import Node, NodePool, Player, Track
from lava_lyra.exceptions import NodeNotAvailable, NodeRestException

from rosetta.utils.queue import Queue
from rosetta.utils.task_lock import TaskRLock

type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)


class CustomPlayer(Player):
    def __init__(
        self, client, channel, *, node=None, node_identifier: str | None = None
    ):
        if node_identifier is not None and node is None:
            node = NodePool.get_node(identifier=node_identifier)
        super().__init__(client, channel, node=node)
        self.queue = Queue[Track]()
        self._mutation_lock = TaskRLock()

    async def play(
        self,
        track: Track,
        *,
        start: int = 0,
        end: int = 0,
        ignore_if_playing: bool = False,
    ) -> Track:
        async with self._mutation_lock:
            return await super().play(
                track,
                start=start,
                end=end,
                ignore_if_playing=ignore_if_playing,
            )

    async def stop(self) -> None:
        async with self._mutation_lock:
            await super().stop()

    async def destroy(self) -> None:
        async with self._mutation_lock:
            await super().destroy()

    async def swap_node(self, new_node: Node) -> None:
        async with self._mutation_lock:
            data: dict[str, JsonValue] | None = None
            if self.current is not None:
                data = {
                    "position": self.position,
                    "track": {"encoded": self.current.track_id},
                    "volume": self._volume,
                    "paused": self._paused,
                }
                if not self.filters.empty:
                    data["filters"] = self.filters.get_all_payloads()

            old_node = self._node
            old_endpoint = self._player_endpoint_uri
            del old_node._players[self._guild.id]
            self._node = new_node
            new_node._players[self._guild.id] = self

            try:
                await self._refresh_endpoint_uri(new_node._session_id)
                await self._dispatch_voice_update()
                if data:
                    await new_node.send(
                        method="PATCH",
                        path=self._player_endpoint_uri,
                        guild_id=self._guild.id,
                        data=data,
                    )
                    if self._log:
                        self._log.info(
                            f"Successfully restored player state on new node {new_node._identifier}"
                        )
            except (NodeNotAvailable, NodeRestException):
                new_endpoint = self._player_endpoint_uri
                new_node._players.pop(self._guild.id, None)
                self._node = old_node
                old_node._players[self._guild.id] = self
                self._player_endpoint_uri = old_endpoint
                try:
                    await new_node.send(
                        method="DELETE",
                        path=new_endpoint,
                        guild_id=self._guild.id,
                    )
                except (NodeNotAvailable, NodeRestException) as cleanup_error:
                    if self._log:
                        self._log.warning(
                            f"Failed to clean up player on node {new_node._identifier}: {cleanup_error}"
                        )
                try:
                    await self._dispatch_voice_update()
                    if data:
                        await old_node.send(
                            method="PATCH",
                            path=old_endpoint,
                            guild_id=self._guild.id,
                            data=data,
                        )
                except (NodeNotAvailable, NodeRestException) as rollback_error:
                    if self._log:
                        self._log.warning(
                            f"Failed to restore player on node {old_node._identifier}: {rollback_error}"
                        )
                raise

            if self._log:
                self._log.info(
                    f"Swapped player from node {old_node._identifier} to {new_node._identifier}"
                )
