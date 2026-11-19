"""Конфигурация AMI. Все настройки через переменные окружения / .env."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень backend/ — относительно него считаются все относительные пути.
BACKEND_DIR = Path(__file__).resolve().parent.parent
# Корень проекта AMI/.
PROJECT_DIR = BACKEND_DIR.parent


def resolve_path(value: str | Path) -> Path:
    """Превращает относительный путь в абсолютный от каталога backend/.

    Это важно на Windows: иначе ``./logs`` и ``./ami.db`` зависят от того,
    из какого каталога запущен процесс (рабочий стол, System32 и т.п.).
    """
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BACKEND_DIR / path
    return path.resolve()


class Settings(BaseSettings):
    """Настройки приложения, читаемые из .env / окружения."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_DIR / ".env"),
        env_file_encoding="utf-8",
        env_prefix="AMI_",
        extra="ignore",
    )

    # --- Окружение ---
    app_name: str = "AMI — Avito Market Intelligence"
    app_version: str = "0.2.0"
    debug: bool = Field(default=False, description="Режим отладки")

    # --- БД ---
    database_url: str = Field(
        default="sqlite:///./ami.db",
        description="URL БД (PostgreSQL или sqlite:///...)",
    )
    db_echo: bool = Field(default=False, description="Логировать SQL-запросы")

    # --- Redis (опционален, только при необходимости) ---
    redis_url: Optional[str] = Field(default=None)

    # --- LLM ---
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        description="Базовый URL Ollama",
    )
    ollama_model: str = Field(
        default="qwen3:1.7b",
        description="Стартовая локальная модель",
    )
    ollama_timeout_s: int = Field(default=180, description="Таймаут вызова Ollama")
    llm_max_tokens: int = Field(default=1024)
    llm_temperature: float = Field(default=0.1)

    # --- ML ---
    ml_model_dir: str = Field(
        default="./models",
        description="Папка для сохранения обученных моделей",
    )
    ml_min_confidence: float = Field(default=0.55, description="Минимальная уверенность прогноза")

    # --- Сбор данных ---
    data_collection_enabled: bool = Field(default=True)
    data_collection_interval_min: int = Field(default=60)
    max_listings_per_source: int = Field(default=5000)
    max_csv_bytes: int = Field(default=10 * 1024 * 1024, description="Лимит размера CSV")
    max_csv_rows: int = Field(default=50_000, description="Лимит строк в CSV")
    request_timeout_s: int = Field(default=30)
    max_retries: int = Field(default=3)

    # --- Аналитика ---
    min_sample: int = Field(
        default=5,
        description="Минимальный размер выборки для оценки/аномалии",
    )

    # --- Сопоставление объявлений с моделями ---
    auto_match_enabled: bool = Field(
        default=True,
        description="Автоматически пытаться определить product_id по тексту",
    )
    match_min_confidence: float = Field(
        default=0.55,
        description="Минимальная уверенность авто-сопоставления",
    )

    # --- API ---
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)
    api_workers: int = Field(default=1, description="Число воркеров; на слабом ПК — 1")
    allowed_origins: str = Field(default="*")

    # --- Telegram (опционален) ---
    telegram_bot_token: Optional[str] = Field(default=None)
    telegram_chat_id: Optional[str] = Field(default=None)

    # --- Безопасность ---
    api_key: Optional[str] = Field(default=None, description="Ключ доступа к API")

    # --- Пути ---
    data_dir: str = Field(default="./data")
    log_dir: str = Field(default="./logs")

    # --- Вычисляемые пути ---
    @property
    def data_path(self) -> Path:
        return resolve_path(self.data_dir)

    @property
    def log_path(self) -> Path:
        return resolve_path(self.log_dir)

    @property
    def ml_model_path(self) -> Path:
        return resolve_path(self.ml_model_dir)

    @property
    def cors_origins(self) -> list[str]:
        """Разбирает AMI_ALLOWED_ORIGINS в список для CORSMiddleware."""
        raw = (self.allowed_origins or "").strip()
        if not raw or raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]


settings = Settings()
