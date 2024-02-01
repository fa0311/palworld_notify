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

    join_broadcast_message: str = Field(
        default="{name} ({steamid}) has joined the server."
    )
    leave_broadcast_message: str = Field(
        default="{name} ({steamid}) has left the server."
    )
    restart_on_last_leave: bool = Field(default=False)

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


class PalworldNotify:
    prev_data: Optional[pd.DataFrame] = None
    prev_data_raw: Optional[pd.DataFrame] = None

    def check(self):
        with Client(env.ip, env.port, passwd=env.password) as client:
            players = client.run("ShowPlayers", enforce_id=False)
            next_data_raw = pd.read_csv(StringIO(players))

            next_data = next_data_raw[next_data_raw["playeruid"] != 0]
            next_data = next_data.drop(columns=["steamid"])

            if self.prev_data is None:
                self.prev_data = next_data
            if self.prev_data_raw is None:
                self.prev_data_raw = next_data_raw

            outer_data = pd.merge(
                next_data,
                self.prev_data,
                how="outer",
                indicator=True,
            )
            outer_raw_data = pd.merge(
                next_data_raw,
                self.prev_data_raw,
                how="outer",
                indicator=True,
            )

            join = outer_data[outer_data["_merge"] == "left_only"]
            leave = outer_data[outer_data["_merge"] == "right_only"]

        with Client(env.ip, env.port, passwd=env.password) as client:
            if not join.empty or not leave.empty:
                logger.info("\n" + outer_data.to_string())

            for _, row in join.iterrows():
                data = outer_raw_data[
                    outer_raw_data["playeruid"] == row["playeruid"]
                ].iloc[0]
                text = env.join_message.format(**data)
                text_broadcast = env.join_broadcast_message.format(**data)
                text_broadcast = text_broadcast.replace(" ", "_")
                client.run("Broadcast", text_broadcast, enforce_id=False)
                if env.line_notify_token:
                    send_line_notify(text)
                if env.discord_webhook_url:
                    send_discord_webhook(text)

            for _, row in leave.iterrows():
                data = outer_raw_data[
                    outer_raw_data["playeruid"] == row["playeruid"]
                ].iloc[0]
                text = env.leave_message.format(**data)
                text_broadcast = env.leave_broadcast_message.format(**data)
                text_broadcast = text_broadcast.replace(" ", "_")
                client.run("Broadcast", text_broadcast, enforce_id=False)
                if env.line_notify_token:
                    send_line_notify(text)
                if env.discord_webhook_url:
                    send_discord_webhook(text)

            if (
                env.restart_on_last_leave
                and next_data.empty
                and not self.prev_data.empty
            ):
                logger.info("Restarting the server...")
                client.run("Save", enforce_id=False)
                client.run("Shutdown", "5", enforce_id=False)

            self.prev_data = next_data
            self.prev_data_raw = next_data_raw


if __name__ == "__main__":
    logger.info("start")
    client = PalworldNotify()

    while True:
        try:
            client.check()
            time.sleep(env.wait_time)
        except Exception as e:
            if __debug__:
                raise e from e
            else:
                logger.error(f"Error: {e}")
                logger.info(f"Restarting in {env.wait_time} seconds...")
                time.sleep(env.wait_time)
