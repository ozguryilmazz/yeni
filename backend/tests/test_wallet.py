from unittest.mock import AsyncMock, patch

from app.services.binance_client import BinanceAPIError

from tests.conftest import connect_credential


def test_balances_without_credential_returns_404(client, auth_headers):
    r = client.get("/api/wallet/balances", headers=auth_headers)
    assert r.status_code == 404


def test_balances_success_filters_zero_amounts(client, auth_headers):
    connect_credential(client, auth_headers)

    spot_resp = {
        "balances": [
            {"asset": "BTC", "free": "0.5", "locked": "0"},
            {"asset": "USDT", "free": "0", "locked": "0"},
        ]
    }
    futures_resp = {
        "assets": [
            {"asset": "USDT", "walletBalance": "100", "availableBalance": "80", "unrealizedProfit": "5"},
            {"asset": "BNB", "walletBalance": "0", "availableBalance": "0", "unrealizedProfit": "0"},
        ]
    }
    funding_resp = [{"asset": "ETH", "free": "1.2", "locked": "0"}]

    with (
        patch("app.api.routes.wallet.get_spot_account", new=AsyncMock(return_value=spot_resp)),
        patch("app.api.routes.wallet.get_futures_account", new=AsyncMock(return_value=futures_resp)),
        patch("app.api.routes.wallet.get_funding_wallet", new=AsyncMock(return_value=funding_resp)),
    ):
        r = client.get("/api/wallet/balances", headers=auth_headers)

    assert r.status_code == 200
    data = r.json()
    assert data["spot"] == [{"asset": "BTC", "free": 0.5, "locked": 0.0}]
    assert len(data["futures"]) == 1
    assert data["futures"][0]["asset"] == "USDT"
    assert data["funding"] == [{"asset": "ETH", "free": 1.2, "locked": 0.0}]
    assert data["credential_label"] == "main"


def test_balances_binance_error_returns_502(client, auth_headers):
    connect_credential(client, auth_headers)

    with (
        patch(
            "app.api.routes.wallet.get_spot_account",
            new=AsyncMock(side_effect=BinanceAPIError("Invalid API-key")),
        ),
        patch("app.api.routes.wallet.get_futures_account", new=AsyncMock(return_value={"assets": []})),
        patch("app.api.routes.wallet.get_funding_wallet", new=AsyncMock(return_value=[])),
    ):
        r = client.get("/api/wallet/balances", headers=auth_headers)

    assert r.status_code == 502
