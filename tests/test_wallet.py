from unittest.mock import patch

import pytest

from app.binance_client import BinanceAPIError
from app.repository import CredentialNotFoundError, get_wallet_summary

from tests.conftest import connect_credential as connect_credential_helper


def test_balances_without_credential_raises(db, user):
    with pytest.raises(CredentialNotFoundError):
        get_wallet_summary(db, user)


def test_balances_filters_zero_amounts(db, user):
    connect_credential_helper(db, user)

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
        patch("app.repository.get_spot_account", return_value=spot_resp),
        patch("app.repository.get_futures_account", return_value=futures_resp),
        patch("app.repository.get_funding_wallet", return_value=funding_resp),
    ):
        summary = get_wallet_summary(db, user)

    assert summary["spot"] == [{"asset": "BTC", "free": 0.5, "locked": 0.0}]
    assert len(summary["futures"]) == 1
    assert summary["futures"][0]["asset"] == "USDT"
    assert summary["funding"] == [{"asset": "ETH", "free": 1.2, "locked": 0.0}]
    assert summary["credential_label"] == "main"


def test_balances_binance_error_propagates(db, user):
    connect_credential_helper(db, user)

    with (
        patch("app.repository.get_spot_account", side_effect=BinanceAPIError("Invalid API-key")),
        patch("app.repository.get_futures_account", return_value={"assets": []}),
        patch("app.repository.get_funding_wallet", return_value=[]),
    ):
        with pytest.raises(BinanceAPIError):
            get_wallet_summary(db, user)
