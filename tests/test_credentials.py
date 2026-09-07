from unittest.mock import patch

import pytest

from app.binance_client import BinanceAPIError
from app.repository import (
    CredentialNotFoundError,
    WithdrawalPermissionError,
    connect_credential,
    delete_credential,
    list_credentials,
)

from tests.conftest import connect_credential as connect_credential_helper


def test_connect_rejects_withdrawal_enabled(db, user):
    with patch("app.repository.get_api_restrictions", return_value={"enableWithdrawals": True}):
        with pytest.raises(WithdrawalPermissionError):
            connect_credential(db, user, "t", "x" * 20, "y" * 20)


def test_connect_accepts_reading_only(db, user):
    credential = connect_credential_helper(db, user)
    assert credential.can_withdraw is False
    assert credential.encrypted_api_key != "x" * 20  # şifrelenmiş olmalı


def test_connect_invalid_key_propagates_binance_error(db, user):
    with patch("app.repository.get_api_restrictions", side_effect=BinanceAPIError("Invalid API-key", -2015)):
        with pytest.raises(BinanceAPIError):
            connect_credential(db, user, "t", "x" * 20, "y" * 20)


def test_list_and_delete_credential(db, user):
    credential = connect_credential_helper(db, user)

    credentials = list_credentials(db, user)
    assert len(credentials) == 1

    delete_credential(db, user, credential.id)
    assert list_credentials(db, user) == []


def test_delete_missing_credential_raises(db, user):
    import uuid

    with pytest.raises(CredentialNotFoundError):
        delete_credential(db, user, uuid.uuid4())
