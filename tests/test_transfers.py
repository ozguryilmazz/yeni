from unittest.mock import patch

import pytest

from app.binance_client import BinanceAPIError
from app.repository import (
    CredentialNotFoundError,
    SameWalletError,
    create_transfer,
    list_transfers,
)
from app.transfer_types import WalletType

from tests.conftest import connect_credential as connect_credential_helper


def test_transfer_without_credential_raises(db, user):
    with pytest.raises(CredentialNotFoundError):
        create_transfer(db, user, "USDT", 10, WalletType.SPOT, WalletType.USDM_FUTURES)


def test_transfer_same_wallet_raises(db, user):
    connect_credential_helper(db, user)
    with pytest.raises(SameWalletError):
        create_transfer(db, user, "USDT", 10, WalletType.SPOT, WalletType.SPOT)


def test_transfer_success_records_tran_id(db, user):
    connect_credential_helper(db, user)

    with patch("app.repository.create_universal_transfer", return_value={"tranId": 999888}) as mock_transfer:
        transfer = create_transfer(db, user, "usdt", "12.5", WalletType.SPOT, WalletType.USDM_FUTURES)

    assert transfer.status == "SUCCESS"
    assert transfer.binance_tran_id == "999888"
    assert transfer.asset == "USDT"

    args, _ = mock_transfer.call_args
    assert args[2] == "MAIN_UMFUTURE"
    assert args[3] == "USDT"
    assert args[4] == "12.5"


def test_transfer_failure_logged_as_failed(db, user):
    connect_credential_helper(db, user)

    with patch(
        "app.repository.create_universal_transfer",
        side_effect=BinanceAPIError("Insufficient balance", -3020),
    ):
        with pytest.raises(BinanceAPIError):
            create_transfer(db, user, "USDT", "99999", WalletType.SPOT, WalletType.USDM_FUTURES)

    history = list_transfers(db, user)
    assert len(history) == 1
    assert history[0].status == "FAILED"
    assert history[0].error_message == "Insufficient balance"


def test_transfer_history_lists_most_recent_first(db, user):
    connect_credential_helper(db, user)

    with patch("app.repository.create_universal_transfer", return_value={"tranId": 1}):
        create_transfer(db, user, "USDT", "1", WalletType.SPOT, WalletType.FUNDING)
    with patch("app.repository.create_universal_transfer", return_value={"tranId": 2}):
        create_transfer(db, user, "USDT", "2", WalletType.FUNDING, WalletType.SPOT)

    history = list_transfers(db, user)
    assert len(history) == 2
    assert history[0].binance_tran_id == "2"
    assert history[1].binance_tran_id == "1"
