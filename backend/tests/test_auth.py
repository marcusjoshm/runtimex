def test_register_returns_token_and_user(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "bob", "email": "bob@example.com", "password": "pw12345"},
    )
    assert response.status_code == 201
    body = response.get_json()
    assert "token" in body and body["token"]
    assert body["user"]["username"] == "bob"
    assert body["user"]["email"] == "bob@example.com"
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


def test_register_rejects_missing_fields(client):
    response = client.post("/api/auth/register", json={"username": "bob"})
    assert response.status_code == 400


def test_register_rejects_duplicate_username(client):
    client.post(
        "/api/auth/register",
        json={"username": "bob", "email": "bob@example.com", "password": "pw12345"},
    )
    response = client.post(
        "/api/auth/register",
        json={"username": "bob", "email": "other@example.com", "password": "pw12345"},
    )
    assert response.status_code == 409


def test_register_rejects_duplicate_email(client):
    client.post(
        "/api/auth/register",
        json={"username": "bob", "email": "bob@example.com", "password": "pw12345"},
    )
    response = client.post(
        "/api/auth/register",
        json={"username": "bob2", "email": "bob@example.com", "password": "pw12345"},
    )
    assert response.status_code == 409


def test_login_with_username(client):
    client.post(
        "/api/auth/register",
        json={"username": "carol", "email": "carol@example.com", "password": "pw12345"},
    )
    response = client.post(
        "/api/auth/login",
        json={"username": "carol", "password": "pw12345"},
    )
    assert response.status_code == 200
    assert response.get_json()["token"]


def test_login_with_email(client):
    client.post(
        "/api/auth/register",
        json={"username": "dave", "email": "dave@example.com", "password": "pw12345"},
    )
    response = client.post(
        "/api/auth/login",
        json={"email": "dave@example.com", "password": "pw12345"},
    )
    assert response.status_code == 200
    assert response.get_json()["token"]


def test_login_rejects_wrong_password(client):
    client.post(
        "/api/auth/register",
        json={"username": "eve", "email": "eve@example.com", "password": "pw12345"},
    )
    response = client.post(
        "/api/auth/login",
        json={"username": "eve", "password": "wrong"},
    )
    assert response.status_code == 401


def test_login_rejects_unknown_user(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "ghost", "password": "anything"},
    )
    assert response.status_code == 401


def test_me_requires_token(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_returns_current_user(client, auth_headers):
    response = client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()["user"]["username"] == "alice"


def test_me_rejects_garbage_token(client):
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code in (401, 422)
