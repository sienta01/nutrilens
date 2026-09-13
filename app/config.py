from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./data/nutrilens.db"
    upload_dir: Path = Path("data/uploads")
    cookie_secure: bool = False
    demo_enabled: bool = True
    session_days: int = 14
    max_upload_bytes: int = 10 * 1024 * 1024
    ai_provider: Literal["gemini", "openai"] = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_polling: bool = False

    @property
    def ai_configured(self) -> bool:
        return bool(self.gemini_api_key if self.ai_provider == "gemini" else self.openai_api_key)

    @property
    def ai_provider_label(self) -> str:
        return "Google Gemini" if self.ai_provider == "gemini" else "OpenAI"

    @property
    def photo_privacy_notice(self) -> str:
        notice = f"Photos, meal descriptions, and portion notes are sent to {self.ai_provider_label} for approximate nutrition estimates."
        if self.ai_provider == "gemini":
            notice += " On Gemini's free tier, Google may use submitted content to improve its products."
        return notice

    @field_validator("gemini_model")
    @classmethod
    def valid_gemini_model(cls, value: str) -> str:
        value = value.strip().removeprefix("models/")
        if not re.fullmatch(r"gemini-[A-Za-z0-9._-]+", value):
            raise ValueError("GEMINI_MODEL must be a Gemini model ID, not a URL.")
        return value

    @field_validator("app_url")
    @classmethod
    def valid_app_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("APP_URL must be an absolute http(s) URL without credentials.")
        return value.rstrip("/")

    @field_validator("telegram_bot_username")
    @classmethod
    def clean_bot_username(cls, value: str) -> str:
        value = value.strip().lstrip("@")
        if value and (not value.replace("_", "").isalnum() or not value.isascii()):
            raise ValueError("Invalid Telegram bot username.")
        return value

    @model_validator(mode="after")
    def public_settings(self):
        if urlsplit(self.app_url).hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}:
            self.demo_enabled = False
        if self.app_url.startswith("https://"):
            self.cookie_secure = True
        return self
