# DriverGuard bot — образ для docker-compose (профиль "full")
FROM python:3.11-slim

WORKDIR /app

# Зависимости отдельным слоем для кеширования
COPY pyproject.toml ./
RUN pip install --no-cache-dir "aiogram>=3.7" "httpx>=0.27" tzdata

COPY main.py ./
COPY dg_bot ./dg_bot

CMD ["python", "main.py"]
