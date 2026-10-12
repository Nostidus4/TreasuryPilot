# API migrations

Alembic migrations for the API-owned PostgreSQL schema live in `versions/`.
Merged migrations are immutable.

Run migrations from the repository root:

```sh
DATABASE_URL=postgresql+asyncpg://... uv run --package treasurypilot-api \
  alembic -c services/api/alembic.ini upgrade head
```

`DATABASE_URL` must use an async SQLAlchemy PostgreSQL driver. The Compose API service
already supplies an `asyncpg` URL.
