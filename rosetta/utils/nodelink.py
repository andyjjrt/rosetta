from lava_lyra import Node
from lava_lyra.exceptions import NodeRestException


def is_missing_player(error: NodeRestException) -> bool:
    return str(error).endswith("404 Not Found: Player not found.")


def is_voice_ready(voice_state: dict) -> bool:
    event = voice_state.get("event")
    return (
        set(voice_state) == {"sessionId", "event"}
        and isinstance(voice_state.get("sessionId"), str)
        and isinstance(event, dict)
        and isinstance(event.get("token"), str)
        and isinstance(event.get("endpoint"), str)
    )


async def delete_remote_player(node: Node, path: str, guild_id: int) -> None:
    try:
        await node.send(method="DELETE", path=path, guild_id=guild_id)
    except NodeRestException as error:
        if not is_missing_player(error):
            raise
