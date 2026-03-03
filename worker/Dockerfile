FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY worker/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir .

COPY worker /app

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "worker_app.main"]
