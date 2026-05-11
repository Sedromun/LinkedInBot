"""
logger.py — централизованная настройка логирования для всего backend.

Использование в любом модуле:
    from backend.logger import get_logger
    log = get_logger(__name__)
    log.info("всё ок")
    log.error("упало", exc_info=True)   # exc_info=True — добавит traceback
"""

import logging
import sys


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def _setup_root_logger() -> None:
    root = logging.getLogger()
    if root.handlers:
        return  # уже настроен

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_build_formatter())
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    # Заглушаем лишний шум от сторонних библиотек
    for noisy in ("httpx", "httpcore", "urllib3", "google", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_setup_root_logger()


def get_logger(name: str) -> logging.Logger:
    """Возвращает настроенный логгер для модуля."""
    return logging.getLogger(name)
