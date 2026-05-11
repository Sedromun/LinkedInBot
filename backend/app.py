"""
FastAPI-приложение: API для генерации и публикации постов + раздача SPA.
Запуск из корня репозитория: uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.env_util import (
    missing_env_keys,
    require_image_env,
    require_linkedin_env,
    require_llm_env,
)
from backend.generator import generate_post_content
from backend.images import generate_image
from backend.linkedin import LinkedInClient
from backend.logger import get_logger
from backend.paths import REPO_ROOT

log = get_logger(__name__)

load_dotenv(REPO_ROOT / ".env")

from backend.proxy import configure_env_proxy

# Если задан SOCKS5_PROXY, заранее пропишем HTTP_PROXY/HTTPS_PROXY/ALL_PROXY,
# чтобы библиотеки на базе httpx/requests корректно использовали прокси.
configure_env_proxy()

FRONTEND_DIR = REPO_ROOT / "frontend"

AspectRatio = Literal["1:1", "16:9", "9:16", "4:3", "3:4"]


class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=4000)


class RunRequest(BaseModel):
    """Полный сценарий: либо topic (сгенерировать текст), либо уже готовые post + image_prompt."""

    topic: str | None = Field(None, max_length=4000)
    post: str | None = None
    image_prompt: str | None = None
    dry_run: bool = False
    no_image: bool = False
    aspect_ratio: AspectRatio = "16:9"


class PublishRequest(BaseModel):
    """Публикация в LinkedIn по уже готовому тексту (и опционально картинке)."""

    post: str = Field(..., min_length=1)
    image_prompt: str | None = None
    no_image: bool = False
    aspect_ratio: AspectRatio = "16:9"


def _has_edited_payload(body: RunRequest) -> bool:
    return bool(
        body.post is not None
        and body.image_prompt is not None
        and body.post.strip()
        and body.image_prompt.strip()
    )


def _resolve_content(body: RunRequest) -> tuple[str, str]:
    if _has_edited_payload(body):
        return body.post.strip(), body.image_prompt.strip()
    if body.topic and body.topic.strip():
        result = generate_post_content(body.topic.strip())
        return result["post"], result["image_prompt"]
    raise HTTPException(
        status_code=422,
        detail="Укажи topic для генерации или оба поля post и image_prompt.",
    )


app = FastAPI(
    title="LinkedIn Auto-Poster API",
    description="Генерация постов (Gemini 2.5 Flash + Google Search), картинка Imagen, публикация в LinkedIn.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/env")
def env_status():
    miss = missing_env_keys()
    return {
        "configured": len(miss) == 0,
        "missing": [{"key": m["key"], "description": m["description"]} for m in miss],
    }


@app.post("/api/generate")
def api_generate(body: GenerateRequest):
    """Только исследование + текст поста и промпт картинки (без картинки и без LinkedIn)."""
    try:
        require_llm_env()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    try:
        result = generate_post_content(body.topic.strip())
    except Exception as e:
        log.exception("Ошибка generate_post_content для темы %r", body.topic)
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {
        "post": result["post"],
        "image_prompt": result["image_prompt"],
        "char_count": len(result["post"]),
    }


@app.post("/api/run")
def api_run(body: RunRequest):
    """
    Полный сценарий: генерация (если нужно), опционально картинка, публикация если не dry_run.
    """
    needs_llm = not _has_edited_payload(body)
    try:
        if needs_llm:
            require_llm_env()
        if not body.no_image:
            require_image_env()
        if not body.dry_run:
            require_linkedin_env()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    try:
        post_text, image_prompt = _resolve_content(body)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Ошибка _resolve_content")
        raise HTTPException(status_code=500, detail=str(e)) from e

    image_path: str | None = None
    image_error: str | None = None

    if not body.no_image:
        try:
            image_path = generate_image(image_prompt, aspect_ratio=body.aspect_ratio)
        except Exception as e:
            log.exception("Ошибка генерации картинки")
            image_error = str(e)
            if not body.dry_run:
                raise HTTPException(
                    status_code=500,
                    detail=f"Не удалось сгенерировать картинку: {e}. Включи «Без картинки» или исправь GOOGLE_API_KEY.",
                ) from e

    if body.dry_run:
        return {
            "dry_run": True,
            "published": False,
            "post": post_text,
            "image_prompt": image_prompt,
            "image_path": image_path,
            "image_error": image_error,
            "char_count": len(post_text),
        }

    try:
        client = LinkedInClient(
            access_token=os.environ["LINKEDIN_ACCESS_TOKEN"],
            person_urn=os.environ["LINKEDIN_PERSON_URN"],
        )
        post_id = client.publish(post_text, image_path)
    except Exception as e:
        log.exception("Ошибка публикации в LinkedIn")
        raise HTTPException(status_code=500, detail=str(e)) from e

    log.info("Пост опубликован: %s", post_id)
    return {
        "dry_run": False,
        "published": True,
        "post_id": post_id,
        "post": post_text,
        "image_prompt": image_prompt,
        "image_path": image_path,
        "char_count": len(post_text),
    }


@app.post("/api/publish")
def api_publish(body: PublishRequest):
    """Опубликовать готовый текст (и при необходимости сгенерировать и прикрепить картинку)."""
    try:
        require_linkedin_env()
        if not body.no_image:
            require_image_env()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    image_path: str | None = None
    if not body.no_image:
        if not body.image_prompt or not body.image_prompt.strip():
            raise HTTPException(
                status_code=422,
                detail="Для публикации с картинкой укажи image_prompt или включи «Без картинки».",
            )
        try:
            image_path = generate_image(body.image_prompt.strip(), aspect_ratio=body.aspect_ratio)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка генерации картинки: {e}") from e

    try:
        client = LinkedInClient(
            access_token=os.environ["LINKEDIN_ACCESS_TOKEN"],
            person_urn=os.environ["LINKEDIN_PERSON_URN"],
        )
        post_id = client.publish(body.post.strip(), image_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {
        "published": True,
        "post_id": post_id,
        "image_path": image_path,
    }


# ── Статика фронтенда (после API-маршрутов) ─────────────────────────────────

if FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.get("/")
def serve_spa():
    index = FRONTEND_DIR / "index.html"
    if not index.is_file():
        return JSONResponse(
            status_code=404,
            content={"detail": f"Нет фронтенда: создай {index}"},
        )
    return FileResponse(index)
