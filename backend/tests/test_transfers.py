from unittest.mock import AsyncMock, patch

from app.services.binance_client import BinanceAPIError

from tests.conftest import connect_credential


def test_transfer_without_credential_returns_404(client, auth_headers):
    r = client.post(
        "/api/transfers",
        json={"asset": "USDT", "amount": "10", "from_wallet": "SPOT", "to_wallet": "USDM_FUTURES"},
        headers=auth_headers,
    )
    assert r.status_code == 404


def test_transfer_same_wallet_rejected(client, auth_headers):
    connect_credential(client, auth_headers)
    r = client.post(
        "/api/transfers",
        json={"asset": "USDT", "amount": "10", "from_wallet": "SPOT", "to_wallet": "SPOT"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_transfer_success_records_tran_id(client, auth_headers):
    connect_credential(client, auth_headers)

    with patch(
        "app.api.routes.transfers.create_universal_transfer", new=AsyncMock(return_value={"tranId": 999888})
    ) as mock_transfer:
        r = client.post(
            "/api/transfers",
            json={"asset": "usdt", "amount": "12.5", "from_wallet": "SPOT", "to_wallet": "USDM_FUTURES"},
            headers=auth_headers,
        )

    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "SUCCESS"
    assert body["binance_tran_id"] == "999888"
    assert body["asset"] == "USDT"

    args, _ = mock_transfer.call_args
    assert args[2] == "MAIN_UMFUTURE"
    assert args[3] == "USDT"
    assert args[4] == "12.5"


def test_transfer_failure_logged_as_failed(client, auth_headers):
    connect_credential(client, auth_headers)

    with patch(
        "app.api.routes.transfers.create_universal_transfer",
        new=AsyncMock(side_effect=BinanceAPIError("Insufficient balance", -3020)),
    ):
        r = client.post(
            "/api/transfers",
            json={"asset": "USDT", "amount": "99999", "from_wallet": "SPOT", "to_wallet": "USDM_FUTURES"},
            headers=auth_headers,
        )
    assert r.status_code == 400

    r = client.get("/api/transfers", headers=auth_headers)
    assert r.status_code == 200
    history = r.json()
    assert len(history) == 1
    assert history[0]["status"] == "FAILED"
    assert history[0]["error_message"] == "Insufficient balance"


def test_transfer_history_lists_most_recent_first(client, auth_headers):
    connect_credential(client, auth_headers)

    with patch("app.api.routes.transfers.create_universal_transfer", new=AsyncMock(return_value={"tranId": 1})):
        client.post(
            "/api/transfers",
            json={"asset": "USDT", "amount": "1", "from_wallet": "SPOT", "to_wallet": "FUNDING"},
            headers=auth_headers,
        )
    with patch("app.api.routes.transfers.create_universal_transfer", new=AsyncMock(return_value={"tranId": 2})):
        client.post(
            "/api/transfers",
            json={"asset": "USDT", "amount": "2", "from_wallet": "FUNDING", "to_wallet": "SPOT"},
            headers=auth_headers,
        )

    r = client.get("/api/transfers", headers=auth_headers)
    history = r.json()
    assert len(history) == 2
    assert history[0]["binance_tran_id"] == "2"
    assert history[1]["binance_tran_id"] == "1"
