FROM python:3.11-slim

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 messaging && \
    useradd --uid 10001 --gid messaging --create-home --shell /usr/sbin/nologin messaging

COPY worker/pyproject.toml /tmp/pyproject.toml
RUN python -c "import pathlib, tomllib; data = tomllib.loads(pathlib.Path('/tmp/pyproject.toml').read_text(encoding='utf-8')); deps = data.get('project', {}).get('dependencies', []); pathlib.Path('/tmp/requirements.txt').write_text('\n'.join(deps) + '\n', encoding='utf-8')" && \
    pip install --no-cache-dir --retries 10 --timeout 180 -r /tmp/requirements.txt

COPY --chown=messaging:messaging worker /app

USER messaging

CMD ["python", "-m", "worker_app.main"]
