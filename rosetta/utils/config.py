import configparser
import os

config = configparser.ConfigParser()
config.read("config.ini")

# Bot config - prefer environment variables, fallback to config.ini
TOKEN = os.environ.get("BOT_TOKEN") or config.get("bot", "TOKEN", fallback=None)
CLIENT_ID = os.environ.get("BOT_CLIENT_ID") or config.get("bot", "CLIENT_ID", fallback=None)


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
        if config.has_section("llm"):
            return config.get("llm", key, fallback=None)
        return None


LLM = LLMConfig()

# Langfuse config - prefer environment variables, fallback to config.ini
if os.environ.get("LANGFUSE_PUBLIC_KEY"):
    pass  # Already set in environment
elif config.has_section("langfuse"):
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", config["langfuse"].get("PUBLIC_KEY"))
    os.environ.setdefault("LANGFUSE_SECRET_KEY", config["langfuse"].get("SECRET_KEY"))
    os.environ.setdefault("LANGFUSE_HOST", config["langfuse"].get("HOST"))
