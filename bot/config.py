"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_SYSTEM_PROMPT = (
    "Ты — дружелюбный ассистент в групповом чате Telegram. "
    "Тебе передают последние сообщения чата в формате «Имя: текст», "
    "чтобы ты понимал контекст разговора. Отвечай только на последнюю "
    "реплику, обращённую к тебе. Пиши кратко и по делу, на языке "
    "собеседника. Не используй Markdown-разметку — Telegram покажет её "
    "как обычный текст. Не начинай ответ со своего имени и не подписывайся."
)


def _env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Environment variable {name} is required but not set")
    return value or ""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    openai_api_key: str
    openai_base_url: str | None
    model: str
    system_prompt: str
    temperature: float
    max_tokens: int

    # Which prefixes wake the bot up, e.g. "ии" -> "ии привет"
    trigger_prefixes: tuple[str, ...]

    db_path: str
    history_limit: int
    history_max_chars: int
    log_all_messages: bool
    clear_requires_admin: bool

    # Typewriter effect
    edit_interval: float
    min_delta_chars: int
    cursor: str

    request_timeout: float

    @classmethod
    def from_env(cls) -> "Settings":
        prefixes = tuple(
            p.strip().lower()
            for p in _env("TRIGGER_PREFIXES", "ии").split(",")
            if p.strip()
        )
        if not prefixes:
            prefixes = ("ии",)

        return cls(
            bot_token=_env("TELEGRAM_BOT_TOKEN", required=True),
            openai_api_key=_env("OPENAI_API_KEY", required=True),
            openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
            model=_env("OPENAI_MODEL", "gpt-4o-mini"),
            system_prompt=_env("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
            temperature=_env_float("OPENAI_TEMPERATURE", 0.7),
            max_tokens=_env_int("OPENAI_MAX_TOKENS", 1024),
            trigger_prefixes=prefixes,
            db_path=_env("DB_PATH", "data/bot.db"),
            history_limit=_env_int("HISTORY_LIMIT", 40),
            history_max_chars=_env_int("HISTORY_MAX_CHARS", 12000),
            log_all_messages=_env_bool("LOG_ALL_MESSAGES", True),
            clear_requires_admin=_env_bool("CLEAR_REQUIRES_ADMIN", False),
            edit_interval=_env_float("TYPEWRITER_INTERVAL", 1.1),
            min_delta_chars=_env_int("TYPEWRITER_MIN_CHARS", 24),
            cursor=_env("TYPEWRITER_CURSOR", "▍"),
            request_timeout=_env_float("OPENAI_TIMEOUT", 120.0),
        )
