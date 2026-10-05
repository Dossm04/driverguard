# Backend DriverGuard — FastAPI на uvicorn
FROM python:3.11-slim

WORKDIR /srv/app

# Шрифт с кириллицей для PDF-отчётов (BE-14)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Не писать .pyc и не буферизовать вывод
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Сначала метаданные проекта — слой с зависимостями кэшируется
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
COPY docker-entrypoint.sh ./

RUN pip install --no-cache-dir . && chmod +x docker-entrypoint.sh

EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --retries=20 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=4)" || exit 1

# Миграции + seed (SEED=auto|always|never) + uvicorn
CMD ["./docker-entrypoint.sh"]
