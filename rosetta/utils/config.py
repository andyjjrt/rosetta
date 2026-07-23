from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSetting(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="BOT_", extra="ignore"
    )

    TOKEN: str | None = None
    CLIENT_ID: str | None = None
    DEBUG: bool = False


# Cog-specific disable flags
class CogSetting(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="COG_", extra="ignore"
    )

    BASICS_DISABLE: bool = False
    MUSIC_DISABLE: bool = False
    MYGO_DISABLE: bool = False
    LLM_DISABLE: bool = False


# Emoji config - fetched from application emojis at startup
class EmojiSetting(BaseSettings):
    model_config = SettingsConfigDict(extra="allow")

    def set_emojis(self, emojis: dict[str, str]):
        for key, value in emojis.items():
            object.__setattr__(self, key, value)

    def get(self, key: str) -> str:
        return getattr(self, key, "")


# LLM config - prefer environment variables
class LLMSetting(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="LLM_", extra="ignore"
    )

    BASE_URL: str | None = None
    API_KEY: str | None = None
    DEFAULT_MODEL: str | None = None
    IMAGE_API_KEY: str | None = None
    IMAGE_MODEL: str = "dall-e-3"


class LangfuseSetting(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LANGFUSE_",
        extra="ignore",
    )

    PUBLIC_KEY: str | None = None
    SECRET_KEY: str | None = None
    HOST: str | None = None


# Lavalink config - prefer environment variables
class LavaLinkSetting(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LAVALINK_",
        extra="ignore",
    )

    # Set to "k8s" to enable Kubernetes service discovery, "local" for local development
    DISCOVERY_MODE: str = "local"

    # Local development settings
    HOST: str = "127.0.0.1"
    PORT: int = 2333
    PASSWORD: str = "youshallnotpass"
    LOCAL_NODE_COUNT: int = Field(default=2, ge=1)

    # Kubernetes discovery settings
    K8S_NAMESPACE: str = "default"
    K8S_SERVICE_NAME: str = "lavalink"
    K8S_SERVICE_PORT: int = 2333


BotConfig = BotSetting()
EmojiConfig = EmojiSetting()
LLMConfig = LLMSetting()
LangfuseConfig = LangfuseSetting()
LavaLinkConfig = LavaLinkSetting()
CogConfig = CogSetting()
