FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir . && \
    pip install --no-cache-dir pytest pytest-asyncio aiosqlite asgi-lifespan

COPY backend /app

ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "alembic upgrade head && python -m app.db.bootstrap_schema && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
