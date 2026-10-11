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
RUN uv sync --frozen --no-dev --package treasurypilot-signer

USER 65532:65532
EXPOSE 8080
CMD ["uvicorn", "treasurypilot_signer.main:app", "--host", "0.0.0.0", "--port", "8080"]
