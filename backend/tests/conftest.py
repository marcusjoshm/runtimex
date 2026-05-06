import os
import sys
from pathlib import Path

import pytest

# Ensure the backend package directory is importable when pytest is invoked from repo root.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")


@pytest.fixture
def app():
    import auth as auth_module
    import main as main_module

    main_module.app.config["TESTING"] = True

    auth_module.users.clear()
    auth_module.email_index.clear()

    yield main_module.app

    auth_module.users.clear()
    auth_module.email_index.clear()


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
