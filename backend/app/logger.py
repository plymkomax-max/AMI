"""Логирование AMI: один корневой обработчик на консоль и файл.

Важно: при импорте модуля ничего не пишется на диск. Настройка выполняется
явно через ``setup_logging()`` (вызывается при старте приложения).
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(lineno)4d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def _formatter(with_color: bool = False) -> logging.Formatter:
    if with_color:
        try:
            import colorlog

            return colorlog.ColoredFormatter(
                "%(bold_white)s%(asctime)s%(reset)s | "
                + "%(log_color)s%(levelname)-8s%(reset)s | "
                + "%(bold_cyan)s%(name)s%(reset)s | "
                + "%(blue)s%(lineno)4d%(reset)s | "
                + "%(message)s",
                datefmt=DATE_FORMAT,
                log_colors={
                    "DEBUG": "white",
                    "INFO": "green",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "bold_red",
                },
            )
        except ImportError:
            pass
    return logging.Formatter(LOG_FORMAT, DATE_FORMAT)


def setup_logging(log_dir: str | Path | None = None) -> Path:
    """Настраивает корневой логгер. Повторный вызов безопасен.

    Возвращает путь к каталогу логов.
    """
    global _configured

    directory = Path(log_dir) if log_dir is not None else settings.log_path
    directory.mkdir(parents=True, exist_ok=True)

    if _configured:
        return directory

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)

    # Убираем обработчики, которые могли остаться от basicConfig/других библиотек
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_formatter(with_color=sys.stdout.isatty()))
    root.addHandler(console)

    file_handler = TimedRotatingFileHandler(
        directory / "ami.log",
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setFormatter(_formatter(with_color=False))
    root.addHandler(file_handler)

    # Сторонние библиотеки не должны засорять лог DEBUG-сообщениями
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    _configured = True
    return directory


def get_logger(name: str) -> logging.Logger:
    """Возвращает логгер. Обработчики наследуются от корневого."""
    return logging.getLogger(name)
