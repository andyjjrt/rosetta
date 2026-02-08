from pydantic_settings import BaseSettings


# Bot config - prefer environment variables, fallback to config.ini
class BotSetting(BaseSettings):
    TOKEN: str | None = None
    CLIENT_ID: str | None = None
    DEBUG: bool = False

    class Config:
        env_prefix = "BOT_"


# Emoji config - fetched from application emojis at startup
class EmojiSetting(BaseSettings):
    model_config = {"extra": "allow"}

    def set_emojis(self, emojis: dict[str, str]):
        for key, value in emojis.items():
            object.__setattr__(self, key, value)

    def get(self, key: str) -> str:
        return getattr(self, key, "")


# LLM config - prefer environment variables
class LLMSetting(BaseSettings):
    BASE_URL: str | None = None
    API_KEY: str | None = None
    DEFAULT_MODEL: str | None = None
    IMAGE_API_KEY: str | None = None
    IMAGE_MODEL: str = "dall-e-3"

    class Config:
        env_prefix = "LLM_"


# Lavalink config - prefer environment variables
class LavalinkSetting(BaseSettings):
    # Set to "k8s" to enable Kubernetes service discovery, "local" for local development
    DISCOVERY_MODE: str = "local"

    # Local development settings
    HOST: str = "127.0.0.1"
    PORT: int = 2333
    PASSWORD: str = "youshallnotpass"

    # Kubernetes discovery settings
    K8S_NAMESPACE: str = "default"
    K8S_SERVICE_NAME: str = "lavalink"
    K8S_SERVICE_PORT: int = 2333

    class Config:
        env_prefix = "LAVALINK_"


BotConfig = BotSetting()
EmojiConfig = EmojiSetting()
LLMConfig = LLMSetting()
LavalinkConfig = LavalinkSetting()
