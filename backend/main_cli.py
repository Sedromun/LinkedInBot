"""
CLI — точка входа LinkedIn Auto-Poster (как раньше main.py).

Запуск из корня репозитория:
  python -m backend.main_cli "тема поста"
  python -m backend.main_cli --dry-run "тема"
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from backend.env_util import (
    require_image_env,
    require_linkedin_env,
    require_llm_env,
)
from backend.proxy import configure_env_proxy
from backend.generator import generate_post_content
from backend.images import generate_image
from backend.linkedin import LinkedInClient
from backend.paths import REPO_ROOT

load_dotenv(REPO_ROOT / ".env")
configure_env_proxy()

BOLD = "\033[1m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
DIVIDER = "─" * 56


def banner():
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════╗
║       LinkedIn AI Auto-Poster  🚀                    ║
║  Gemini researches → writes post → Imagen 3 draws    ║
╚══════════════════════════════════════════════════════╝{RESET}
""")


def get_topic(args) -> str:
    if args.topic:
        return " ".join(args.topic).strip()
    print(f"{CYAN}💡 Введи тему для поста:{RESET}")
    topic = input("   → ").strip()
    if not topic:
        print(f"{RED}❌ Тема не может быть пустой{RESET}")
        sys.exit(1)
    return topic


def confirm(prompt: str) -> bool:
    answer = input(f"\n{YELLOW}{prompt} [y/n]: {RESET}").strip().lower()
    return answer in ("y", "yes", "да", "д")


def main():
    banner()

    parser = argparse.ArgumentParser(description="LinkedIn AI Auto-Poster")
    parser.add_argument(
        "topic",
        nargs="*",
        help="Тема поста (можно в кавычках или несколькими словами)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Сгенерировать и показать пост, но НЕ публиковать",
    )
    parser.add_argument(
        "--no-image",
        action="store_true",
        help="Публиковать без картинки (только текст)",
    )
    args = parser.parse_args()

    topic = get_topic(args)
    print(f"\n{BOLD}🎯 Тема:{RESET} {topic}")
    print(DIVIDER)

    print(f"\n{BOLD}📚 Шаг 1/3 — Исследование темы и написание поста{RESET}")
    try:
        require_llm_env()
    except RuntimeError as e:
        print(f"{RED}❌ {e}{RESET}")
        sys.exit(1)
    try:
        result = generate_post_content(topic)
    except Exception as e:
        print(f"{RED}❌ Ошибка генерации контента: {e}{RESET}")
        sys.exit(1)

    post_text = result["post"]
    image_prompt = result["image_prompt"]

    print(f"\n{BOLD}📝 Сгенерированный пост:{RESET}")
    print(DIVIDER)
    print(post_text)
    print(DIVIDER)
    print(f"{CYAN}Символов: {len(post_text)}{RESET}")

    if not args.dry_run:
        if not confirm("✅ Пост выглядит хорошо? Продолжить?"):
            print(f"\n{YELLOW}Отменено.{RESET}")
            sys.exit(0)

    image_path = None
    if not args.no_image:
        print(f"\n{BOLD}🎨 Шаг 2/3 — Генерация изображения (Imagen 3){RESET}")
        try:
            require_image_env()
            image_path = generate_image(image_prompt)
        except Exception as e:
            print(f"{YELLOW}⚠️  Не удалось сгенерировать картинку: {e}{RESET}")
            if not confirm("Опубликовать пост без картинки?"):
                sys.exit(0)
            image_path = None

    if args.dry_run:
        print(f"\n{GREEN}✅ Dry-run завершён. Пост НЕ опубликован.{RESET}")
        if image_path:
            print(f"   Картинка сохранена: {image_path}")
        print(f"\n{CYAN}Промпт картинки:{RESET}")
        print(f"  {image_prompt}")
        return

    print(f"\n{BOLD}📤 Шаг 3/3 — Публикация в LinkedIn{RESET}")

    try:
        require_linkedin_env()
    except RuntimeError as e:
        print(f"{RED}❌ {e}{RESET}")
        sys.exit(1)

    try:
        client = LinkedInClient(
            access_token=os.getenv("LINKEDIN_ACCESS_TOKEN"),
            person_urn=os.getenv("LINKEDIN_PERSON_URN"),
        )
        post_id = client.publish(post_text, image_path)
    except Exception as e:
        print(f"{RED}❌ Ошибка публикации: {e}{RESET}")
        sys.exit(1)

    print(f"\n{GREEN}{BOLD}🎉 Пост успешно опубликован!{RESET}")
    print(f"   ID поста: {post_id}")
    print("   Открой LinkedIn, чтобы посмотреть результат.")


if __name__ == "__main__":
    main()
