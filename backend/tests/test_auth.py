def test_register_login_me_refresh(client):
    r = client.post("/api/auth/register", json={"email": "a@b.com", "password": "password123"})
    assert r.status_code == 201
    tokens = r.json()
    assert "access_token" in tokens and "refresh_token" in tokens

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "a@b.com"

    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "password123"})
    assert r.status_code == 200

    r = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "password123"})
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong-password"})
    assert r.status_code == 401


def test_register_duplicate_email(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "password123"})
    r = client.post("/api/auth/register", json={"email": "a@b.com", "password": "password123"})
    assert r.status_code == 409


def test_me_invalid_token(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_refresh_rejects_access_token(client):
    r = client.post("/api/auth/register", json={"email": "a@b.com", "password": "password123"})
    tokens = r.json()

    r = client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401
