from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROVIDER_LABELS = {"gemini": "Google Gemini", "groq": "Groq", "openai": "OpenAI"}

# A model ID may carry at most one namespace segment, and every segment starts
# alphanumeric, so "..", "/qwen", "a/b/c" and URLs can never redirect an endpoint.
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)?")
_GEMINI_MODEL = re.compile(r"gemini-[A-Za-z0-9._-]+")

# How many AI_n_* failover lines are read from the environment.
AI_LINES = (1, 2, 3)


@dataclass(frozen=True)
class AiLine:
    """One rung of the failover chain: a provider, its own credential, and its model."""

    provider: str
    api_key: str
    model: str


def _clean_model(provider: str, value: str) -> str:
    value = value.strip()
    if provider == "gemini":
        value = value.removeprefix("models/")
        if not _GEMINI_MODEL.fullmatch(value):
            raise ValueError("A gemini line needs a Gemini model ID, not a URL or another provider's model.")
        return value
    if not _MODEL_ID.fullmatch(value):
        raise ValueError(f"A {provider} line needs a plain model ID, not a URL or path.")
    return value


def _build_chain(settings: "Settings") -> list[AiLine]:
    """Ordered lines to try. Explicit AI_n_* lines replace the single-provider settings."""
    lines: list[AiLine] = []
    for index in AI_LINES:
        provider = getattr(settings, f"ai_{index}_provider")
        api_key = getattr(settings, f"ai_{index}_api_key")
        model = getattr(settings, f"ai_{index}_model")
        if not (provider or api_key or model):
            continue
        if not provider or not api_key:
            raise ValueError(f"AI_{index}_PROVIDER and AI_{index}_API_KEY must both be set.")
        resolved = _clean_model(provider, model) if model else getattr(settings, f"{provider}_model")
        lines.append(AiLine(provider, api_key, resolved))
    if lines:
        return lines
    legacy_key = getattr(settings, f"{settings.ai_provider}_api_key")
    if not legacy_key:
        return []
    return [AiLine(settings.ai_provider, legacy_key, getattr(settings, f"{settings.ai_provider}_model"))]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./data/nutrilens.db"
    upload_dir: Path = Path("data/uploads")
    cookie_secure: bool = False
    demo_enabled: bool = True
    session_days: int = 14
    max_upload_bytes: int = 10 * 1024 * 1024
    log_level: str = "INFO"
    # Empty disables file logging; the file rotates so it cannot grow without bound.
    log_file: str = "data/nutrilens.log"
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 3
    ai_provider: Literal["gemini", "openai", "groq"] = "gemini"
    gemini_api_key: str = ""
    # A moving alias: Google retires pinned IDs (gemini-2.5-flash-lite is already
    # closed to new keys), and this keeps working without a config change.
    gemini_model: str = "gemini-flash-latest"
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    # Ordered failover lines. Set these to try several providers or several keys in turn.
    ai_1_provider: str = ""
    ai_1_api_key: str = ""
    ai_1_model: str = ""
    ai_2_provider: str = ""
    ai_2_api_key: str = ""
    ai_2_model: str = ""
    ai_3_provider: str = ""
    ai_3_api_key: str = ""
    ai_3_model: str = ""
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_polling: bool = False

    @property
    def ai_chain(self) -> list[AiLine]:
        return _build_chain(self)

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_chain)

    @property
    def ai_primary_provider(self) -> str:
        """The provider actually tried first, falling back to the single-provider setting."""
        chain = self.ai_chain
        return chain[0].provider if chain else self.ai_provider

    @property
    def ai_provider_label(self) -> str:
        return PROVIDER_LABELS[self.ai_primary_provider]

    @property
    def ai_provider_labels(self) -> list[str]:
        """Distinct provider names on the chain, in order. Two keys for one provider read as one name."""
        labels: list[str] = []
        for line in self.ai_chain:
            label = PROVIDER_LABELS[line.provider]
            if label not in labels:
                labels.append(label)
        return labels

    @property
    def photo_privacy_notice(self) -> str:
        labels = self.ai_provider_labels or [self.ai_provider_label]
        notice = f"Photos, meal descriptions, and portion notes are sent to {labels[0]} for approximate nutrition estimates."
        if len(labels) > 1:
            rest = labels[1] if len(labels) == 2 else ", ".join(labels[1:-1] + [f"then {labels[-1]}"])
            notice += f" If {labels[0]} is out of quota or unavailable, the same photo and notes are sent to {rest}."
        uses_gemini = any(line.provider == "gemini" for line in self.ai_chain) or (
            not self.ai_chain and self.ai_provider == "gemini")
        if uses_gemini:
            notice += " On Gemini's free tier, Google may use submitted content to improve its products."
        return notice

    @field_validator("gemini_model")
    @classmethod
    def valid_gemini_model(cls, value: str) -> str:
        return _clean_model("gemini", value)

    @field_validator("groq_model", "openai_model")
    @classmethod
    def valid_model_id(cls, value: str, info) -> str:
        return _clean_model(info.field_name.removesuffix("_model"), value)

    @field_validator("ai_1_provider", "ai_2_provider", "ai_3_provider")
    @classmethod
    def valid_line_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value and value not in PROVIDER_LABELS:
            raise ValueError(f"Unknown AI provider. Choose one of: {', '.join(PROVIDER_LABELS)}.")
        return value

    @field_validator("ai_1_api_key", "ai_2_api_key", "ai_3_api_key", "ai_1_model", "ai_2_model", "ai_3_model")
    @classmethod
    def strip_line_value(cls, value: str) -> str:
        return value.strip()

    @field_validator("log_level")
    @classmethod
    def valid_log_level(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("LOG_LEVEL must be CRITICAL, ERROR, WARNING, INFO, or DEBUG.")
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
        # Surface a malformed failover line at startup rather than on the first upload.
        _build_chain(self)
        return self
