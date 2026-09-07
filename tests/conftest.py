import os
import tempfile

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="binance_wallet_test_")
os.environ.setdefault("BINANCE_APP_DATA_DIR", _TEST_DATA_DIR)
# Qt widget testleri ekran/masaüstü olmadan (CI, bu sandbox) çalışabilsin diye.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from app import models  # noqa: E402,F401
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.repository import register_user  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def user(db):
    return register_user(db, "test@example.com", "password123")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def connect_credential(db, user, can_withdraw: bool = False):
    from unittest.mock import patch

    from app.repository import connect_credential as _connect_credential

    with patch("app.repository.get_api_restrictions", return_value={"enableWithdrawals": can_withdraw}):
        return _connect_credential(db, user, "main", "x" * 20, "y" * 20)
