# syntax=docker/dockerfile:1.7
FROM python:3.11-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 messaging && \
    useradd --uid 10001 --gid messaging --create-home --shell /usr/sbin/nologin messaging

COPY worker/pyproject.toml worker/requirements.lock /tmp/
RUN --mount=type=cache,id=messaging-worker-pip,target=/root/.cache/pip \
    pip install --only-binary=:all: --retries 10 --timeout 180 -r /tmp/requirements.lock

COPY --chown=messaging:messaging worker /app

USER messaging

CMD ["python", "-m", "worker_app.main"]
