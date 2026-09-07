from unittest.mock import AsyncMock, patch

from app.services.binance_client import BinanceAPIError


def test_connect_rejects_withdrawal_enabled(client, auth_headers):
    with patch(
        "app.api.routes.credentials.get_api_restrictions",
        new=AsyncMock(return_value={"enableWithdrawals": True}),
    ):
        r = client.post(
            "/api/credentials",
            json={"label": "t", "api_key": "x" * 20, "api_secret": "y" * 20},
            headers=auth_headers,
        )
    assert r.status_code == 400


def test_connect_accepts_reading_only(client, auth_headers):
    with patch(
        "app.api.routes.credentials.get_api_restrictions",
        new=AsyncMock(return_value={"enableWithdrawals": False}),
    ):
        r = client.post(
            "/api/credentials",
            json={"label": "t", "api_key": "x" * 20, "api_secret": "y" * 20},
            headers=auth_headers,
        )
    assert r.status_code == 201
    body = r.json()
    assert body["can_withdraw"] is False
    assert "api_key" not in body
    assert "api_secret" not in body
    assert "encrypted_api_key" not in body


def test_connect_invalid_key_returns_400(client, auth_headers):
    with patch(
        "app.api.routes.credentials.get_api_restrictions",
        new=AsyncMock(side_effect=BinanceAPIError("Invalid API-key, IP, or permissions", -2015)),
    ):
        r = client.post(
            "/api/credentials",
            json={"label": "t", "api_key": "x" * 20, "api_secret": "y" * 20},
            headers=auth_headers,
        )
    assert r.status_code == 400


def test_list_and_delete_credential(client, auth_headers):
    with patch(
        "app.api.routes.credentials.get_api_restrictions",
        new=AsyncMock(return_value={"enableWithdrawals": False}),
    ):
        r = client.post(
            "/api/credentials",
            json={"label": "t", "api_key": "x" * 20, "api_secret": "y" * 20},
            headers=auth_headers,
        )
    cred_id = r.json()["id"]

    r = client.get("/api/credentials", headers=auth_headers)
    assert r.status_code == 200 and len(r.json()) == 1

    r = client.delete(f"/api/credentials/{cred_id}", headers=auth_headers)
    assert r.status_code == 204

    r = client.get("/api/credentials", headers=auth_headers)
    assert len(r.json()) == 0


def test_delete_missing_credential_returns_404(client, auth_headers):
    r = client.delete("/api/credentials/00000000-0000-0000-0000-000000000000", headers=auth_headers)
    assert r.status_code == 404
