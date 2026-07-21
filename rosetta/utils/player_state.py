from dataclasses import dataclass

from lava_lyra import Filter, Node, Track


@dataclass(frozen=True)
class PlayerSnapshot:
    node: Node
    session_id: str | None
    endpoint_uri: str
    epoch: int
    recovery_generation: int
    current: Track | None
    position: int
    volume: int
    paused: bool
    filters: dict[str, object] | None
    filter_objects: tuple[Filter, ...]

    def payload(self) -> dict[str, object] | None:
        if self.current is None:
            return None
        return {
            "position": self.position,
            "track": {"encoded": self.current.track_id},
            "volume": self.volume,
            "paused": self.paused,
            "filters": self.filters,
        }
