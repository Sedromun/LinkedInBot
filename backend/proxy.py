"""
proxy.py — централизованная настройка SOCKS5 прокси.

Читает SOCKS5_PROXY из .env и применяет ко всем HTTP-клиентам:
  - requests  (auth.py, linkedin.py)
  - httpx/google-genai  (generator.py, images.py) — через env-переменные
"""

import os


def get_proxies() -> dict | None:
    """
    Возвращает словарь прокси для requests, или None если SOCKS5_PROXY не задан.

    Использование:
        session.proxies.update(get_proxies() or {})
        requests.get(url, proxies=get_proxies())
    """
    proxy = os.getenv("SOCKS5_PROXY", "").strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def configure_env_proxy() -> None:
    """
    Прописывает SOCKS5_PROXY в стандартные переменные окружения,
    чтобы httpx (и google-genai внутри него) подхватил прокси автоматически.

    Вызывать ДО создания genai.Client().
    """
    proxy = os.getenv("SOCKS5_PROXY", "").strip()
    if not proxy:
        return
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ[var] = proxy
