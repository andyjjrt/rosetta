import sys

from .basics import Basics
from .llm import LLM
from .music import Music
from .mygo import Mygo
from .setting import Setting

try:
    from .nanobot import Nanobot
except ModuleNotFoundError:
    if "rosetta.commands.nanobot" not in sys.modules:
        raise

__all__ = ["Admin", "Basics", "LLM", "Mygo", "Music", "Nanobot", "Setting"]
