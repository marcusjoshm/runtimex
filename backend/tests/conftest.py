import os
import sys
from pathlib import Path

import pytest

# Ensure the backend package directory is importable when pytest is invoked from repo root.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
# Default to in-memory DB for the unit-test fixture; tests that need on-disk
# persistence (test_persistence.py) override via build_app_with_db.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


def _reset_db_for(app):
    """Drop and recreate every table on the given app's bound DB."""
    from db import db
    with app.app_context():
        db.drop_all()
        db.create_all()


@pytest.fixture
def app():
    """Per-test Flask app with a clean in-memory DB.

    Reuses the singleton ``main.app`` (importing it twice triggers Flask
    blueprint-already-registered errors), but drops and recreates every
    table between tests so no state leaks across them.
    """
    import main as main_module

    main_module.app.config["TESTING"] = True

    _reset_db_for(main_module.app)
    # Reset the in-memory scheduler cache too -- otherwise dataclass objects
    # from the previous test linger and confuse "is this experiment new?" logic.
    main_module.scheduler.reset_cache()

    yield main_module.app

    _reset_db_for(main_module.app)
    main_module.scheduler.reset_cache()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers(client):
    """Register a default test user and return Authorization headers."""
    response = client.post(
        "/api/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "secret123"},
    )
    assert response.status_code == 201, response.get_json()
    token = response.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def register_user(client, username: str, email: str = None, password: str = "secret123"):
    """Helper: register a user and return Authorization headers.

    Used by permission tests that need a second (or third) account distinct
    from the default ``auth_headers`` Alice. Idempotent for re-registration
    (returns 201 on first call only).
    """
    email = email or f"{username}@example.com"
    response = client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert response.status_code == 201, response.get_json()
    token = response.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def second_user_headers(client):
    """Register a second user (``bob``) and return Authorization headers.

    Use alongside ``auth_headers`` for share/permission tests where two
    distinct users need to act on the same experiment.
    """
    return register_user(client, "bob", "bob@example.com", "secret456")
