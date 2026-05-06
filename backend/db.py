"""SQLAlchemy bootstrap for runtimex.

Single module-level `db = SQLAlchemy()` instance, plus an `init_db(app)` helper
that wires the URI and creates tables. Call `init_db(app)` once at startup
(or per-test via the conftest fixture).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from flask_sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

# Module-level singleton -- imported by models.py for `class Foo(db.Model)`.
db = SQLAlchemy()


def init_db(app, database_uri: Optional[str] = None) -> None:
    """Configure ``app`` for SQLAlchemy, init the extension, and create tables.

    ``database_uri`` overrides the env / default. Useful for tests that want
    a fresh in-memory or per-tmp_path DB without mutating ``os.environ``.
    """
    uri = (
        database_uri
        or os.environ.get("DATABASE_URL")
        or "sqlite:///runtimex.db"
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    # In-memory SQLite needs a single shared connection; otherwise each new
    # connection opens an empty DB and the tables we just created vanish.
    if uri == "sqlite:///:memory:" or uri.endswith(":memory:"):
        from sqlalchemy.pool import StaticPool
        app.config.setdefault(
            "SQLALCHEMY_ENGINE_OPTIONS",
            {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            },
        )

    # Importing models registers them with `db.metadata` so create_all sees them.
    # Local import avoids circular import at module load: models.py imports `db`
    # from this file.
    import models  # noqa: F401  (registers ORM classes)

    # `db.init_app` is idempotent only if called against a fresh app; in tests we
    # may re-call init_db on the same app to reset, so guard against the
    # "already registered" assertion by checking the extension registry.
    if "sqlalchemy" not in app.extensions:
        db.init_app(app)

    with app.app_context():
        db.create_all()


def reset_db(app) -> None:
    """Drop all tables and recreate. Test-only helper."""
    with app.app_context():
        db.drop_all()
        db.create_all()
