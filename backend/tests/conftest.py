import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_MASTER_KEY", "test-encryption-master-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_pytest.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ApiCredential, Transfer, User  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/auth/register", json={"email": "test@example.com", "password": "password123"})
    tokens = response.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def connect_credential(client: TestClient, headers: dict[str, str], can_withdraw: bool = False) -> str:
    from unittest.mock import AsyncMock, patch

    with patch(
        "app.api.routes.credentials.get_api_restrictions",
        new=AsyncMock(return_value={"enableWithdrawals": can_withdraw}),
    ):
        response = client.post(
            "/api/credentials",
            json={"label": "main", "api_key": "x" * 20, "api_secret": "y" * 20},
            headers=headers,
        )
    return response.json()["id"]
