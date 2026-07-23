import logging

from discord.ext import commands
from lava_lyra import NodePool

from rosetta.models.node import NodeConfig
from rosetta.utils.config import LavaLinkConfig

logger = logging.getLogger("rosetta")


class HybridNodePool(NodePool):
    def __init__(self):
        super().__init__()

    def _get_k8s_endpoints(self) -> list[NodeConfig]:
        """
        Discover Lavalink nodes from Kubernetes Endpoints.
        Returns a list of dicts with host, port, password, and identifier.
        """
        try:
            from kubernetes import client
            from kubernetes import config as k8s_config

            # Try in-cluster config first (when running inside k8s)
            try:
                k8s_config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes config")
            except k8s_config.ConfigException:
                # Fall back to kubeconfig (for local development with k8s)
                k8s_config.load_kube_config()
                logger.info("Loaded kubeconfig for Kubernetes access")

            v1 = client.CoreV1Api()
            namespace = LavaLinkConfig.K8S_NAMESPACE
            service_name = LavaLinkConfig.K8S_SERVICE_NAME
            port = LavaLinkConfig.K8S_SERVICE_PORT
            password = LavaLinkConfig.PASSWORD

            # Get endpoints for the lavalink service
            endpoints = v1.read_namespaced_endpoints(
                name=service_name, namespace=namespace
            )

            nodes: list[NodeConfig] = []
            if endpoints.subsets:
                for subset in endpoints.subsets:
                    if subset.addresses:
                        for address in subset.addresses:
                            node_id = address.ip
                            node_name = address.node_name
                            if address.target_ref:
                                node_id = address.target_ref.name
                            nodes.append(
                                NodeConfig(
                                    node_name=node_name,
                                    identifier=node_id,
                                    host=address.ip,
                                    port=port,
                                    password=password,
                                )
                            )
                            logger.info(
                                f"Discovered Lavalink node: {node_id} at {address.ip}:{port} in {node_name}"
                            )

            if not nodes:
                logger.warning(
                    f"No Lavalink endpoints found in {namespace}/{service_name}"
                )

            return nodes

        except ImportError:
            logger.error("kubernetes package not installed, cannot use k8s discovery")
            return []
        except Exception as e:
            logger.error(f"Failed to discover Lavalink nodes from Kubernetes: {e}")
            return []

    def _get_local_endpoints(self) -> list[NodeConfig]:
        """
        Get node configuration for local development. Use with docker-compose.dev.yaml.
        Returns a list with a single node based on environment config.
        """
        return [
            NodeConfig(
                node_name="localhost",
                identifier=f"MAIN-{i}",
                host=LavaLinkConfig.HOST,
                port=LavaLinkConfig.PORT + i,
                password=LavaLinkConfig.PASSWORD,
            )
            for i in range(LavaLinkConfig.LOCAL_NODE_COUNT)
        ]

    def _get_nodes(self) -> list[NodeConfig]:
        if LavaLinkConfig.DISCOVERY_MODE == "k8s":
            nodes = self._get_k8s_endpoints()
            if not nodes:
                nodes = self._get_local_endpoints()
        else:
            nodes = self._get_local_endpoints()
        return nodes

    async def create_nodes(self, bot: commands.Bot):
        nodes = self._get_nodes()
        for node in nodes:
            identifier = f"{node.identifier} ({node.node_name})"
            await self.create_node(
                bot=bot,
                identifier=identifier,
                host=node.host,
                port=node.port,
                password=node.password,
            )

    async def destroy_guild_players(self, guild_id: int) -> None:
        for node in self.nodes.values():
            player = node.get_player(guild_id)
            if player is not None:
                await player.destroy()

    async def delete_nodes(self):
        nodes = list(self._nodes.values())
        for node in nodes:
            await node.disconnect()
