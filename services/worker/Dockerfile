FROM ghcr.io/astral-sh/uv:0.11.3 AS uv

FROM python:3.12.13-slim-bookworm
COPY --from=uv /uv /uvx /bin/
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
COPY packages/py-core packages/py-core
COPY services/api services/api
COPY services/worker services/worker
COPY services/signer services/signer
RUN uv sync --frozen --no-dev --package treasurypilot-worker

RUN groupadd --gid 65532 app \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin app

USER app
CMD ["celery", "-A", "treasurypilot_worker.celery_app:app", "worker", "--loglevel=INFO", "--queues=core", "--hostname=core@%h"]
