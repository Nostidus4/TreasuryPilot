from __future__ import annotations

from sqlalchemy.exc import IntegrityError


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the violated constraint for psycopg (``diag``) and asyncpg (wrapped cause)."""

    orig = exc.orig
    for source in (getattr(orig, "diag", None), orig, getattr(orig, "__cause__", None)):
        name = getattr(source, "constraint_name", None)
        if name:
            return str(name)
    return None
