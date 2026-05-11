"""
linkedin.py — клиент для LinkedIn API.

Умеет:
  - Загружать изображение в LinkedIn (register → upload → get asset URN)
  - Создавать текстовый пост
  - Создавать пост с картинкой
"""

import os
import requests
from pathlib import Path

from backend.logger import get_logger
from backend.proxy import get_proxies

log = get_logger(__name__)


class LinkedInClient:
    BASE_URL = "https://api.linkedin.com/v2"

    def __init__(self, access_token: str, person_urn: str):
        self.person_urn = person_urn
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": "202502",
        })
        if proxies := get_proxies():
            self.session.proxies.update(proxies)

    # ── Шаг 1: Зарегистрировать загрузку изображения ────────────────────────

    def _register_image_upload(self) -> tuple[str, str]:
        """Возвращает (upload_url, asset_urn)."""
        payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": self.person_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        resp = self.session.post(
            f"{self.BASE_URL}/assets?action=registerUpload",
            json=payload,
        )
        self._raise_for_status(resp, "Регистрация загрузки изображения")
        data = resp.json()["value"]
        upload_url = (
            data["uploadMechanism"]
            ["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]
            ["uploadUrl"]
        )
        asset_urn = data["asset"]
        return upload_url, asset_urn

    # ── Шаг 2: Загрузить бинарный файл изображения ──────────────────────────

    def _upload_image_binary(self, upload_url: str, image_path: str):
        with open(image_path, "rb") as f:
            image_data = f.read()

        # Для загрузки — отдельная сессия без лишних заголовков
        resp = requests.put(
            upload_url,
            data=image_data,
            headers={
                "Authorization": self.session.headers["Authorization"],
                "Content-Type": "application/octet-stream",
            },
            proxies=get_proxies(),
        )
        # LinkedIn возвращает 201 или 200 при успехе
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Ошибка загрузки изображения: {resp.status_code} {resp.text}"
            )

    # ── Публичный метод: загрузить изображение → получить asset URN ─────────

    def upload_image(self, image_path: str) -> str:
        """Загружает изображение и возвращает asset URN для вставки в пост."""
        size_kb = Path(image_path).stat().st_size // 1024
        log.info("Регистрирую загрузку картинки: %s (%d KB)", Path(image_path).name, size_kb)
        upload_url, asset_urn = self._register_image_upload()

        log.info("Загружаю бинарный файл в LinkedIn…")
        self._upload_image_binary(upload_url, image_path)

        log.info("Картинка загружена: %s", asset_urn)
        return asset_urn

    # ── Создать пост ─────────────────────────────────────────────────────────

    def create_post(self, text: str, asset_urn: str | None = None) -> str:
        """
        Создаёт пост в LinkedIn.
        Если передан asset_urn — публикует с картинкой.
        Возвращает ID поста.
        """
        if asset_urn:
            media_category = "IMAGE"
            media = [
                {
                    "status": "READY",
                    "media": asset_urn,
                }
            ]
        else:
            media_category = "NONE"
            media = []

        payload = {
            "author": self.person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": media_category,
                    **({"media": media} if media else {}),
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }

        resp = self.session.post(f"{self.BASE_URL}/ugcPosts", json=payload)
        self._raise_for_status(resp, "Создание поста")

        post_id = resp.headers.get("X-RestLi-Id", "unknown")
        return post_id

    # ── Удобный комбо-метод ──────────────────────────────────────────────────

    def publish(self, text: str, image_path: str | None = None) -> str:
        """
        Полный цикл: [загрузить картинку] → опубликовать пост.
        Возвращает ID поста.
        """
        asset_urn = None
        if image_path and os.path.exists(image_path):
            asset_urn = self.upload_image(image_path)

        post_id = self.create_post(text, asset_urn)
        return post_id

    # ── Вспомогалка: красивые ошибки ────────────────────────────────────────

    @staticmethod
    def _raise_for_status(resp: requests.Response, action: str):
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            log.error(
                "LinkedIn API ошибка [%s]: HTTP %d\nURL: %s\nОтвет: %s",
                action, resp.status_code, resp.url, detail,
            )
            raise RuntimeError(
                f"LinkedIn API ошибка [{action}]: HTTP {resp.status_code}\n{detail}"
            )
