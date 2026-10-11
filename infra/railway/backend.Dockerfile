FROM python:3.11-slim
WORKDIR /srv/app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/scripts ./scripts
COPY infra/railway/start_backend.py ./deployment/start_backend.py
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["python", "deployment/start_backend.py"]
