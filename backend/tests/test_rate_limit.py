def test_login_is_rate_limited_after_repeated_attempts(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "password123"})

    for _ in range(10):
        r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong"})
        assert r.status_code == 401

    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong"})
    assert r.status_code == 429
