"""
auth.py — однократный OAuth 2.0 flow для получения LinkedIn access token.

Запуск: python -m backend.auth

После успешной авторизации скрипт:
  1. Выведет ACCESS_TOKEN и PERSON_URN в консоль
  2. Автоматически запишет их в .env файл в корне репозитория
"""

import os
import json
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

from backend.paths import REPO_ROOT
from backend.proxy import get_proxies

ENV_FILE = str(REPO_ROOT / ".env")
load_dotenv(ENV_FILE)

CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:8080/callback"
SCOPE = "openid profile w_member_social"

# ── Локальный сервер для перехвата callback ──────────────────────────────────

auth_code: str | None = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family:sans-serif;text-align:center;padding:60px">
                <h2>&#10003; &#1040;&#1074;&#1090;&#1086;&#1088;&#1080;&#1079;&#1072;&#1094;&#1080;&#1103; &#1091;&#1089;&#1087;&#1077;&#1096;&#1085;&#1072;!</h2>
                <p>&#1052;&#1086;&#1078;&#1085;&#1086; &#1079;&#1072;&#1082;&#1088;&#1099;&#1090;&#1100; &#1074;&#1082;&#1083;&#1072;&#1076;&#1082;&#1091; &#1080; &#1074;&#1077;&#1088;&#1085;&#1091;&#1090;&#1100;&#1089;&#1103; &#1074; &#1090;&#1077;&#1088;&#1084;&#1080;&#1085;&#1072;&#1083;.</p>
                </body></html>
            """)
        else:
            error = params.get("error_description", ["Unknown error"])[0]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"<h2>Ошибка: {error}</h2>".encode())

    def log_message(self, format, *args):
        pass  # Отключаем стандартный лог сервера


# ── Шаг 1: Открыть браузер для авторизации ──────────────────────────────────


def get_auth_url() -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": "random_state_string",
    }
    return "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(params)


# ── Шаг 2: Обменять code на access_token ────────────────────────────────────


def exchange_code_for_token(code: str) -> dict:
    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        proxies=get_proxies(),
    )
    resp.raise_for_status()
    return resp.json()


# ── Шаг 3: Получить Person URN через /userinfo ───────────────────────────────


def get_person_urn(access_token: str) -> str:
    resp = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        proxies=get_proxies(),
    )
    resp.raise_for_status()
    data = resp.json()
    sub = data.get("sub", "")  # sub — это person ID
    name = data.get("name", "")
    print(f"\n👤 Авторизован как: {name}")
    return f"urn:li:person:{sub}"


# ── Запись в .env ────────────────────────────────────────────────────────────


def save_to_env(access_token: str, person_urn: str):
    # Создаём .env если нет
    env_path = Path(ENV_FILE)
    if not env_path.exists():
        env_path.write_text("", encoding="utf-8")

    set_key(ENV_FILE, "LINKEDIN_ACCESS_TOKEN", access_token)
    set_key(ENV_FILE, "LINKEDIN_PERSON_URN", person_urn)
    print(f"\n✅ Токен и URN сохранены в {ENV_FILE}")


# ── Главный flow ─────────────────────────────────────────────────────────────


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("❌ Не заданы LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET в .env")
        return

    auth_url = get_auth_url()
    print("🌐 Открываю браузер для авторизации LinkedIn...")
    print(f"   Если браузер не открылся, перейди по ссылке:\n   {auth_url}\n")
    webbrowser.open(auth_url)

    # Запускаем локальный сервер для перехвата кода
    server = HTTPServer(("localhost", 8080), CallbackHandler)
    print("⏳ Ожидаю callback от LinkedIn на http://localhost:8080/callback ...")
    server.handle_request()  # Обрабатываем один запрос и выходим

    if not auth_code:
        print("❌ Не удалось получить authorization code")
        return

    print("\n🔄 Обмениваю code на access_token...")
    token_data = exchange_code_for_token(auth_code)

    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 0)

    print(f"✅ access_token получен (истекает через {expires_in // 86400} дней)")

    person_urn = get_person_urn(access_token)
    print(f"✅ Person URN: {person_urn}")

    save_to_env(access_token, person_urn)

    print("\n" + "─" * 50)
    print("Теперь можно запускать сервер: uvicorn backend.app:app --reload")
    print("─" * 50)


if __name__ == "__main__":
    main()
