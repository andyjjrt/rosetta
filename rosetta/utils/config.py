import configparser
import os

config = configparser.ConfigParser()
config.read("config.ini")

TOKEN = config["bot"].get("TOKEN")
LLM = config["llm"]

if config.has_section("langfuse"):
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", config["langfuse"].get("PUBLIC_KEY"))
    os.environ.setdefault("LANGFUSE_SECRET_KEY", config["langfuse"].get("SECRET_KEY"))
    os.environ.setdefault("LANGFUSE_HOST", config["langfuse"].get("HOST"))
