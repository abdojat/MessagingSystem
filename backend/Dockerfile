FROM python:3.11-slim

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml /tmp/pyproject.toml
RUN python -c "import pathlib, tomllib; data = tomllib.loads(pathlib.Path('/tmp/pyproject.toml').read_text(encoding='utf-8')); deps = data.get('project', {}).get('dependencies', []); pathlib.Path('/tmp/requirements.txt').write_text('\n'.join(deps) + '\n', encoding='utf-8')" && \
    pip install --no-cache-dir --retries 10 --timeout 180 -r /tmp/requirements.txt

COPY backend /app
COPY worker /worker

ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "alembic upgrade head && python -m app.db.bootstrap_schema && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
