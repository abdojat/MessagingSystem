FROM python:3.11-slim

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY worker/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir --retries 10 --timeout 180 .

COPY worker /app

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "worker_app.main"]
