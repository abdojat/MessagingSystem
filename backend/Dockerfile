# syntax=docker/dockerfile:1.7
FROM python:3.11-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 messaging && \
    useradd --uid 10001 --gid messaging --create-home --shell /usr/sbin/nologin messaging && \
    mkdir -p /data/uploads && chown -R messaging:messaging /data/uploads

COPY backend/pyproject.toml backend/requirements.lock /tmp/
RUN --mount=type=cache,id=messaging-backend-pip,target=/root/.cache/pip \
    pip install --only-binary=:all: --retries 10 --timeout 180 -r /tmp/requirements.lock

COPY --chown=messaging:messaging backend /app
COPY --chown=messaging:messaging worker /worker
COPY --chown=messaging:messaging scripts /app/scripts

USER messaging

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-max-size ${WS_MAX_INBOUND_MESSAGE_BYTES:-16384}"]
