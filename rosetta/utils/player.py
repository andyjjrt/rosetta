import asyncio

from lava_lyra import Node, NodePool, Player, Track
from lava_lyra.exceptions import NodeNotAvailable, NodeRestException

from rosetta.utils.nodelink import (
    delete_remote_player,
    is_missing_player,
    is_voice_ready,
)
from rosetta.utils.player_state import PlayerSnapshot
from rosetta.utils.queue import Queue
from rosetta.utils.task_lock import TaskRLock


class CustomPlayer(Player):
    def __init__(
        self, client, channel, *, node=None, node_identifier: str | None = None
    ):
        if node_identifier is not None and node is None:
            node = NodePool.get_node(identifier=node_identifier)
        super().__init__(client, channel, node=node)
        self.queue = Queue[Track]()

        self._recovery_lock = TaskRLock()
        self._mutation_epoch = 0
        self._recovery_generation = 0
        self._terminal = False
        self._repairing_task: asyncio.Task | None = None

    def _snapshot(self) -> PlayerSnapshot:
        return PlayerSnapshot(
            node=self._node,
            session_id=self._node._session_id,
            endpoint_uri=self._player_endpoint_uri,
            epoch=self._mutation_epoch,
            recovery_generation=self._recovery_generation,
            current=self.current,
            position=self.position,
            volume=self._volume,
            paused=self._paused,
            filters=(
                self.filters.get_all_payloads() if not self.filters.empty else None
            ),
            filter_objects=tuple(self._filters._filters),
        )

    def _can_recover(self, snapshot: PlayerSnapshot) -> bool:
        return (
            not self._terminal
            and self._is_connected
            and self._node is snapshot.node
            and self._node._session_id == snapshot.session_id
            and self._player_endpoint_uri == snapshot.endpoint_uri
            and self._mutation_epoch == snapshot.epoch
            and self._node._players.get(self._guild.id) is self
            and is_voice_ready(self._voice_state)
        )

    async def _recover_remote_player(
        self, snapshot: PlayerSnapshot, original_error: NodeRestException
    ) -> None:
        if not self._can_recover(snapshot):
            raise original_error

        await delete_remote_player(snapshot.node, snapshot.endpoint_uri, self._guild.id)
        if not self._can_recover(snapshot):
            raise original_error

        await self._dispatch_voice_update()
        if not self._can_recover(snapshot):
            raise original_error

        if payload := snapshot.payload():
            await snapshot.node.send(
                method="PATCH",
                path=snapshot.endpoint_uri,
                guild_id=self._guild.id,
                data=payload,
            )

        self._recovery_generation += 1
        if self._log:
            self._log.warning(
                f"Recreated missing player on NodeLink node {snapshot.node._identifier}"
            )

    async def _send_player_request(
        self, data: dict, method: str = "PATCH", query: str | None = None
    ) -> object:
        async with self._recovery_lock:
            snapshot = self._snapshot()
            request_data = data.copy()
            try:
                return await super()._send_player_request(data.copy(), method, query)
            except NodeRestException as error:
                if (
                    method != "PATCH"
                    or not self._node._is_nodelink
                    or not is_missing_player(error)
                    or self._repairing_task is asyncio.current_task()
                ):
                    raise

                if self._recovery_generation == snapshot.recovery_generation:
                    await self._recover_remote_player(snapshot, error)
                elif not self._can_recover(snapshot):
                    raise error

                return await snapshot.node.send(
                    method=method,
                    path=snapshot.endpoint_uri,
                    guild_id=self._guild.id,
                    data=request_data,
                    query=query,
                )

    async def play(
        self,
        track: Track,
        *,
        start: int = 0,
        end: int = 0,
        ignore_if_playing: bool = False,
    ) -> Track:
        async with self._recovery_lock:
            snapshot = self._snapshot()
            try:
                return await super().play(
                    track,
                    start=start,
                    end=end,
                    ignore_if_playing=ignore_if_playing,
                )
            except NodeRestException as error:
                self._filters._filters = list(snapshot.filter_objects)
                if (
                    not self._node._is_nodelink
                    or not is_missing_player(error)
                    or self._repairing_task is asyncio.current_task()
                ):
                    raise

                if self._recovery_generation == snapshot.recovery_generation:
                    await self._recover_remote_player(snapshot, error)
                elif not self._can_recover(snapshot):
                    raise error

                self._repairing_task = asyncio.current_task()
                try:
                    return await super().play(
                        track,
                        start=start,
                        end=end,
                        ignore_if_playing=ignore_if_playing,
                    )
                finally:
                    self._repairing_task = None

    async def stop(self) -> None:
        async with self._recovery_lock:
            self._mutation_epoch += 1
            self._current = None
            data = (
                {"track": {"encoded": None}}
                if self._node._is_nodelink
                else {"encodedTrack": None}
            )
            try:
                await self._node.send(
                    method="PATCH",
                    path=self._player_endpoint_uri,
                    guild_id=self._guild.id,
                    data=data,
                )
            except NodeRestException as error:
                if not self._node._is_nodelink or not is_missing_player(error):
                    raise
                snapshot = self._snapshot()
                await delete_remote_player(
                    snapshot.node, snapshot.endpoint_uri, self._guild.id
                )
                if self._can_recover(snapshot):
                    await self._dispatch_voice_update()

    async def destroy(self) -> None:
        self._terminal = True
        self._mutation_epoch += 1
        async with self._recovery_lock:
            try:
                await super().destroy()
            except NodeRestException as error:
                if not self._node._is_nodelink or not is_missing_player(error):
                    raise

    async def swap_node(self, new_node: Node) -> None:
        """Handle swapping to a new node, pr is in pending"""
        async with self._recovery_lock:
            self._mutation_epoch += 1
            data = self._snapshot().payload()
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
                raise

            if self._log:
                self._log.info(
                    f"Swapped player from node {old_node._identifier} to {new_node._identifier}"
                )
