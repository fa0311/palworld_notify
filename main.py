import logging
import os
import time
from enum import Enum
from io import StringIO
from logging import handlers
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from rcon.source import Client


class LogLevel(str, Enum):
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    WARN = "WARN"
    INFO = "INFO"
    DEBUG = "DEBUG"
    NOTSET = "NOTSET"


class Settings(BaseSettings):
    def __init__(self):
        super().__init__()

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    ip: str = Field(default="127.0.0.1")
    port: int = Field(default=25575)
    password: Optional[str] = Field(default=None)

    line_notify_api: str = Field(default="https://notify-api.line.me/api/notify")
    line_notify_token: Optional[str] = Field(default=None)

    discord_webhook_url: Optional[str] = Field(default=None)

    join_message: str = Field(default="{name} ({steamid}) has joined the server.")
    leave_message: str = Field(default="{name} ({steamid}) has left the server.")

    wait_time: int = Field(default=5)
    log_level: LogLevel = Field(default=LogLevel.INFO)


def set_logger(level: LogLevel, path: Path) -> logging.Logger:
    os.makedirs(path.parent, exist_ok=True)
    file_handler = handlers.TimedRotatingFileHandler(
        filename=path,
        when="D",
        interval=1,
        backupCount=90,
        encoding="utf-8",
    )
    file_handler.setLevel(level.value)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level.value)
    logging.basicConfig(
        level=level.value,
        handlers=[file_handler, stream_handler],
    )
    return logging.getLogger(__name__)


env = Settings()
logger = set_logger(env.log_level, Path("logs", "main.log"))


def send_line_notify(notification_message: str):
    assert env.line_notify_api
    assert env.line_notify_token
    headers = {"Authorization": f"Bearer {env.line_notify_token}"}
    data = {"message": notification_message}
    requests.post(env.line_notify_api, headers=headers, data=data)


def send_discord_webhook(notification_message: str):
    assert env.discord_webhook_url
    json = {"content": notification_message}
    requests.post(env.discord_webhook_url, json=json)


def main():
    left_data, right_data = None, None

    with Client(env.ip, env.port, passwd=env.password) as client:
        while True:
            players = client.run("ShowPlayers", enforce_id=False)
            right_data_raw = pd.read_csv(StringIO(players))
            right_data = right_data_raw[right_data_raw["playeruid"] != 0]

            left_data = right_data if left_data is None else left_data

            outer_data = pd.merge(
                right_data,
                left_data,
                how="outer",
                indicator=True,
            )

            join = outer_data[outer_data["_merge"] == "left_only"]
            leave = outer_data[outer_data["_merge"] == "right_only"]

            if not join.empty or not leave.empty:
                logger.info("\n" + outer_data.to_string())

            for _, row in join.iterrows():
                text = env.join_message.format(**row)
                if env.line_notify_token:
                    send_line_notify(text)
                if env.discord_webhook_url:
                    send_discord_webhook(text)

            for _, row in leave.iterrows():
                text = env.leave_message.format(**row)
                if env.line_notify_token:
                    send_line_notify(text)
                if env.discord_webhook_url:
                    send_discord_webhook(text)

            left_data = right_data
            time.sleep(env.wait_time)


if __name__ == "__main__":
    logger.info("start")

    while True:
        try:
            main()
        except Exception as e:
            if __debug__:
                raise e from e
            else:
                logger.error(f"Error: {e}")
                logger.info(f"Restarting in {env.wait_time} seconds...")
                time.sleep(env.wait_time)
