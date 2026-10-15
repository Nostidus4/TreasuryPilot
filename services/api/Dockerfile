FROM ghcr.io/astral-sh/uv:0.11.3 AS uv

FROM python:3.12.13-slim-bookworm
COPY --from=uv /uv /uvx /bin/
WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y xmlsec1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
COPY packages/py-core packages/py-core
COPY services/api services/api
COPY services/worker services/worker
COPY services/signer services/signer
COPY deployments deployments
RUN uv sync --frozen --no-dev --package treasurypilot-api

USER 65532:65532
EXPOSE 8000
CMD ["uvicorn", "treasurypilot_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
