"""
OAuth service для многопользовательского режима.

Поток:
  1. start_oauth(user)  → генерит state, сохраняет в БД, возвращает URL
  2. complete_oauth(...) → по state находит юзера, обменивает code, сохраняет токены
"""

import secrets
import urllib.parse

import requests

from backend.config import settings
from backend.db import crud
from backend.db.models import User
from backend.db.session import session_scope
from backend.logger import get_logger
from backend.proxy import get_proxies

# В mock-режиме токен живёт 60 дней «по бумажке»
_MOCK_TOKEN_TTL_SEC = 60 * 24 * 3600

log = get_logger(__name__)

SCOPE = "openid profile w_member_social"


async def mock_authorize(tg_id: int) -> User:
    """
    DEV-режим: моментально «привязывает» LinkedIn с фейк-токеном.
    Реальные API LinkedIn не дёргаются.
    """
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            raise RuntimeError(f"User tg={tg_id} не найден")

        fake_token = "mock_token_" + secrets.token_urlsafe(16)
        fake_urn   = f"urn:li:person:mock-{tg_id}"
        await crud.save_linkedin_tokens(
            session, user,
            access_token=fake_token,
            person_urn=fake_urn,
            expires_in_sec=_MOCK_TOKEN_TTL_SEC,
        )
        log.info("MOCK OAuth | user=%s urn=%s (без реального LinkedIn)", tg_id, fake_urn)
        return user


async def start_oauth(user: User) -> str:
    """Генерит state, сохраняет в БД, возвращает auth URL для пользователя."""
    state = secrets.token_urlsafe(24)

    async with session_scope() as session:
        # подгружаем юзера в текущей сессии (тот, что в аргументе — из другой)
        db_user = await crud.get_user_by_tg(session, user.telegram_id)
        if not db_user:
            raise RuntimeError(f"User tg={user.telegram_id} не найден в БД")
        await crud.set_oauth_state(session, db_user, state)

    params = {
        "response_type": "code",
        "client_id":     settings.linkedin_client_id,
        "redirect_uri":  settings.oauth_redirect_uri,
        "scope":         SCOPE,
        "state":         state,
    }
    url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(params)
    log.info("OAuth start | user=%s state=%s", user.telegram_id, state[:8])
    return url


def exchange_code(code: str) -> dict:
    """Меняет code на access_token (синхронно — requests)."""
    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  settings.oauth_redirect_uri,
            "client_id":     settings.linkedin_client_id,
            "client_secret": settings.linkedin_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        proxies=get_proxies(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_person_urn(access_token: str) -> str:
    """Получает urn:li:person:... через /userinfo."""
    resp = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        proxies=get_proxies(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    sub = data.get("sub", "")
    return f"urn:li:person:{sub}"


async def complete_oauth(state: str, code: str) -> User:
    """
    Завершает OAuth-обмен. Находит юзера по state, сохраняет токены, возвращает User.

    Бросает RuntimeError если state не найден.
    """
    async with session_scope() as session:
        user = await crud.get_user_by_oauth_state(session, state)
        if not user:
            raise RuntimeError(f"OAuth state не найден или истёк: {state[:8]}…")

        log.info("OAuth callback | user=%s state=%s", user.telegram_id, state[:8])

        token_data = exchange_code(code)
        access_token = token_data["access_token"]
        expires_in   = token_data.get("expires_in", 0)

        person_urn = fetch_person_urn(access_token)

        await crud.save_linkedin_tokens(
            session, user,
            access_token=access_token,
            person_urn=person_urn,
            expires_in_sec=expires_in,
        )
        log.info("OAuth saved | user=%s urn=%s expires_in=%dd",
                 user.telegram_id, person_urn, expires_in // 86400)
        return user
