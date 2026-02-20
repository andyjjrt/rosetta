from pydantic import BaseModel


class NodeConfig(BaseModel):
    node_name: str
    identifier: str
    host: str
    port: int
    password: str
