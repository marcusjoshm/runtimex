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
        _run_migrations()


def reset_db(app) -> None:
    """Drop all tables and recreate. Test-only helper."""
    with app.app_context():
        db.drop_all()
        db.create_all()
        _run_migrations()


def _run_migrations() -> None:
    """Idempotent migrations that run after ``db.create_all()``.

    Currently:
      - Ensures ``steps.condition_id`` column exists (SQLite ALTER TABLE).
        ``create_all`` skips existing tables, so dev DBs created before the
        Conditions plan need this fixup. New DBs already have the column.
      - For each Experiment without any Conditions, creates a default "Main"
        Condition and assigns the Experiment's existing Steps to it.

    This function MUST be called inside an app context.
    """
    from sqlalchemy import inspect, text
    import uuid as _uuid
    from datetime import datetime as _dt

    bind = db.engine
    inspector = inspect(bind)

    # 1. Ensure steps.condition_id column exists. SQLite ALTER TABLE ADD COLUMN
    #    is idempotent only via inspection; do it once if missing.
    if "steps" in inspector.get_table_names():
        step_cols = {c["name"] for c in inspector.get_columns("steps")}
        if "condition_id" not in step_cols:
            logger.info("Adding steps.condition_id column (legacy DB upgrade)")
            with bind.begin() as conn:
                conn.execute(text("ALTER TABLE steps ADD COLUMN condition_id TEXT"))

    # 2. Backfill: every Experiment without any Conditions gets a "Main"
    #    Condition; that Experiment's Steps inherit its id.
    if "experiments" in inspector.get_table_names() and "conditions" in inspector.get_table_names():
        with bind.begin() as conn:
            experiments_lacking_conditions = conn.execute(
                text(
                    "SELECT e.id FROM experiments e "
                    "LEFT JOIN conditions c ON c.experiment_id = e.id "
                    "WHERE c.id IS NULL"
                )
            ).fetchall()

            for (exp_id,) in experiments_lacking_conditions:
                main_id = str(_uuid.uuid4())
                conn.execute(
                    text(
                        "INSERT INTO conditions (id, experiment_id, name, color, order_index, description, created_at) "
                        "VALUES (:id, :exp_id, 'Main', 'slate', 0, NULL, :ts)"
                    ),
                    {"id": main_id, "exp_id": exp_id, "ts": _dt.utcnow()},
                )
                conn.execute(
                    text(
                        "UPDATE steps SET condition_id = :cid WHERE experiment_id = :exp_id"
                    ),
                    {"cid": main_id, "exp_id": exp_id},
                )
                logger.info("Backfilled Main condition %s for experiment %s", main_id, exp_id)
