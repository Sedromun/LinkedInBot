# Один образ для двух сервисов (api и bot) — команда задаётся в compose.
FROM python:3.12-slim

# Утилиты для healthcheck и сборки asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gcc \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend

# Создаём директории для рантайма (БД, картинки)
RUN mkdir -p /app/backend/data /app/backend/generated_images

EXPOSE 8000

# Команда переопределяется в docker-compose (api / bot)
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
