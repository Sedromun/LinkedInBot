"""
FastAPI-приложение для многопользовательского режима:
  - /oauth/callback   — приём OAuth-колбэков от LinkedIn (PROD-режим)
  - /api/health       — healthcheck для docker / мониторинга
  - /api/admin/stats  — метрики (юзеры, генерации, выручка)

Запуск:
  uvicorn backend.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.db.session import init_db
from backend.logger import get_logger
from backend.paths import REPO_ROOT
from backend.proxy import configure_env_proxy
from backend.services import oauth_service

load_dotenv(REPO_ROOT / ".env")
configure_env_proxy()

log = get_logger(__name__)


app = FastAPI(
    title="LinkedIn Auto-Poster API",
    description="OAuth callback + admin stats для многопользовательского бота.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _on_startup() -> None:
    await init_db()


# ── Healthcheck ──────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── Admin / monitoring ───────────────────────────────────────────────────────

@app.get("/api/admin/stats")
async def admin_stats():
    """
    Базовые метрики: юзеры, генерации по статусам, выручка.
    TODO для прода: закрыть auth-токеном или вынести на internal-only порт.
    """
    from sqlalchemy import func as sa_func, select

    from backend.db.models import Generation, GenerationStatus, Payment, User
    from backend.db.session import session_scope

    async with session_scope() as session:
        total_users = (await session.execute(select(sa_func.count(User.id)))).scalar() or 0
        authorized = (
            await session.execute(
                select(sa_func.count(User.id)).where(User.linkedin_access_token.is_not(None))
            )
        ).scalar() or 0

        gen_stats = {}
        for status in GenerationStatus:
            cnt = (
                await session.execute(
                    select(sa_func.count(Generation.id)).where(Generation.status == status)
                )
            ).scalar() or 0
            gen_stats[status.value] = cnt

        total_revenue_cents = (
            await session.execute(select(sa_func.coalesce(sa_func.sum(Payment.amount_cents), 0)))
        ).scalar() or 0
        total_spent_cents = (
            await session.execute(select(sa_func.coalesce(sa_func.sum(Generation.cost_cents), 0)))
        ).scalar() or 0

    return {
        "users": {"total": total_users, "authorized": authorized},
        "generations": gen_stats,
        "money": {
            "topups_usd": total_revenue_cents / 100,
            "spent_usd": total_spent_cents / 100,
        },
    }


# ── Multi-user OAuth callback ────────────────────────────────────────────────

_OAUTH_OK_HTML = """\
<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>LinkedIn привязан</title>
<style>body{font-family:-apple-system,sans-serif;text-align:center;padding:60px;background:#0a0e1a;color:#e2e8f0}
h1{color:#10b981}p{color:#94a3b8}</style></head>
<body><h1>&check; LinkedIn привязан!</h1>
<p>Возвращайся в Telegram-бот и нажми /generate.</p>
<p>Это окно можно закрыть.</p></body></html>
"""

_OAUTH_ERR_HTML = """\
<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Ошибка</title>
<style>body{font-family:-apple-system,sans-serif;text-align:center;padding:60px;background:#0a0e1a;color:#e2e8f0}
h1{color:#ef4444}p{color:#94a3b8}code{{background:#1e293b;padding:8px;border-radius:6px;display:inline-block}}</style></head>
<body><h1>Ошибка при привязке LinkedIn</h1><p><code>{error}</code></p>
<p>Вернись в Telegram-бот и нажми /start заново.</p></body></html>
"""


@app.get("/oauth/callback")
async def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """LinkedIn редиректит сюда после согласия пользователя (только PROD-режим)."""
    if error:
        log.warning("OAuth callback error: %s", error)
        return Response(
            content=_OAUTH_ERR_HTML.format(error=error),
            media_type="text/html",
            status_code=400,
        )
    if not code or not state:
        return Response(
            content=_OAUTH_ERR_HTML.format(error="missing code/state"),
            media_type="text/html",
            status_code=400,
        )

    try:
        user = await oauth_service.complete_oauth(state=state, code=code)
    except Exception as e:
        log.exception("OAuth completion failed")
        return Response(
            content=_OAUTH_ERR_HTML.format(error=str(e)),
            media_type="text/html",
            status_code=400,
        )

    # Уведомим юзера в Telegram, если бот запущен в этом же процессе
    try:
        from backend.bot.notifier import notify_oauth_success
        await notify_oauth_success(user.telegram_id)
    except Exception:
        log.exception("Не удалось уведомить пользователя в Telegram (возможно бот в другом процессе)")

    return Response(content=_OAUTH_OK_HTML, media_type="text/html")
