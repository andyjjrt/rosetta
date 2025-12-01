import os

# Bot config - prefer environment variables, fallback to config.ini
TOKEN = os.environ.get("BOT_TOKEN")
CLIENT_ID = os.environ.get("BOT_CLIENT_ID")


# Emoji config - fetched from application emojis at startup
class EmojiConfig:
    _emojis: dict[str, str] = {}

    @classmethod
    def set_emojis(cls, emojis: dict[str, str]):
        cls._emojis = emojis

    @classmethod
    def get(cls, key: str) -> str:
        return cls._emojis.get(key, "")


EMOJI = EmojiConfig()


# LLM config - prefer environment variables, fallback to config.ini
class LLMConfig:
    @staticmethod
    def get(key: str) -> str | None:
        env_map = {
            "BASE_URL": "LLM_BASE_URL",
            "API_KEY": "LLM_API_KEY",
            "DEFAULT_MODEL": "LLM_DEFAULT_MODEL",
        }
        env_key = env_map.get(key)
        if env_key and os.environ.get(env_key):
            return os.environ.get(env_key)
        return None


LLM = LLMConfig()
