import datetime
import json
import logging
import logging.config
import uuid
from typing import Optional

import discord
from pydantic import BaseModel, Field


class LogContext(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: int
    user_name: str
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None
    command: str = "unknown"

    class Config:
        frozen = True

    @classmethod
    def from_interaction(cls, interaction: discord.Interaction, **kwargs):
        cmd_name = "unknown"
        if interaction.command:
            cmd_name = interaction.command.name
        elif interaction.data and "custom_id" in interaction.data:
            cmd_name = f"ui:{interaction.data['custom_id']}"

        return cls(
            user_id=interaction.user.id,
            user_name=str(interaction.user),
            guild_id=interaction.guild.id if interaction.guild else None,
            channel_id=interaction.channel.id if interaction.channel else None,
            command=cmd_name,
            **kwargs,
        )


class PydanticAdapter(logging.LoggerAdapter):
    def __init__(self, logger, context: LogContext):
        super().__init__(logger, context.model_dump(exclude_none=True))

    def process(self, msg, kwargs):
        extra = self.extra.copy()
        if "extra" in kwargs:
            extra.update(kwargs["extra"])
        kwargs["extra"] = extra
        return msg, kwargs

# --- 1. 自定義 JSON Formatter ---
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            # 這裡可以加入更多標準欄位，如 filename, lineno
        }

        # 如果有 Exception，加入 traceback
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        # 動態抓取由 Adapter 注入的欄位 (Context)
        # 這些欄位名稱必須與 LogContext 的欄位名稱一致
        context_keys = ["request_id", "user_id", "user_name", "guild_id", "channel_id", "command"]
        for key in context_keys:
            if hasattr(record, key):
                log_record[key] = getattr(record, key)

        # 處理額外透過 extra={} 傳入的參數
        # (這裡簡化處理，實際專案可能需要排除上面的保留字)
        
        return json.dumps(log_record, ensure_ascii=False)

# --- 2. 設定函式 ---
def setup_logging(dev_mode: bool = True):
    """
    初始化 Logging 設定
    :param dev_mode: True 使用人類可讀格式，False 使用 JSON 格式 (適合 Docker/K8s)
    """
    
    # 根據環境選擇 Handler
    active_handler = "console_human" if dev_mode else "console_json"
    active_level = "DEBUG" if dev_mode else "INFO"

    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "()": JsonFormatter, # 引用上面的 Class
            },
        },
        "handlers": {
            "console_human": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
            "console_json": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            # 你的 Bot Logger
            "bot": {
                "handlers": [active_handler],
                "level": active_level,
                "propagate": False,
            },
            # Discord.py 的 Logger (避免太吵，設為 WARNING 或 INFO)
            "discord.client": {
                "handlers": [active_handler],
                "level": "WARNING", 
                "propagate": False,
            },
            "discord.gateway": {
                "handlers": [active_handler],
                "level": "WARNING", 
                "propagate": False,
            },
        },
        # Root Logger (捕捉其他所有套件的 log)
        "root": {
            "handlers": [active_handler],
            "level": "INFO",
        }
    }

    logging.config.dictConfig(LOGGING_CONFIG)