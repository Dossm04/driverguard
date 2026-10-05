# DriverGuard device — образ симулятора для демо (без камеры и MediaPipe: только --simulate)
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml config.yaml ./
COPY dg ./dg
RUN pip install --no-cache-dir numpy pyyaml requests

# DG_API_URL / DG_SERIAL / DG_SECRET — из compose; --speedup ускоряет поток событий
CMD ["python", "-m", "dg", "--simulate", "--speedup", "5", "--gps", "sim"]
