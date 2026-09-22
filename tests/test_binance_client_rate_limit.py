import pytest

from app.binance_client import MAX_RATE_LIMIT_RETRIES, BinanceAPIError, _raise_for_error, _request_with_retry


class FakeResponse:
    def __init__(self, status_code: int, headers: dict | None = None, json_data: dict | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


class FakeClient:
    def __init__(self, responses: list[FakeResponse]):
        self._responses = responses
        self.calls = 0

    def get(self, path, params=None):
        self.calls += 1
        return self._responses[self.calls - 1]


def test_request_with_retry_returns_immediately_on_success():
    client = FakeClient([FakeResponse(200)])

    response = _request_with_retry(client, "GET", "/fapi/v1/klines")

    assert response.status_code == 200
    assert client.calls == 1


def test_request_with_retry_retries_429_using_retry_after_header(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    client = FakeClient([FakeResponse(429, headers={"Retry-After": "3"}), FakeResponse(200)])

    response = _request_with_retry(client, "GET", "/fapi/v1/klines")

    assert response.status_code == 200
    assert client.calls == 2
    assert sleeps == [3.0]


def test_request_with_retry_uses_exponential_backoff_when_no_retry_after_header(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    client = FakeClient([FakeResponse(429), FakeResponse(429), FakeResponse(200)])

    response = _request_with_retry(client, "GET", "/fapi/v1/klines")

    assert response.status_code == 200
    assert client.calls == 3
    assert sleeps == [1.0, 2.0]  # 2**0, 2**1


def test_request_with_retry_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    client = FakeClient([FakeResponse(429)] * (MAX_RATE_LIMIT_RETRIES + 1))

    response = _request_with_retry(client, "GET", "/fapi/v1/klines")

    assert response.status_code == 429
    assert client.calls == MAX_RATE_LIMIT_RETRIES + 1


def test_request_with_retry_never_retries_418_ip_ban():
    # 429'ları görmezden gelip tekrar denemeye devam etmenin cezası 418'dir --
    # bunu yeniden denemek yasağı UZATABİLİR, o yüzden asla otomatik denenmez.
    client = FakeClient([FakeResponse(418, headers={"Retry-After": "120"})])

    response = _request_with_retry(client, "GET", "/fapi/v1/klines")

    assert response.status_code == 418
    assert client.calls == 1


def test_raise_for_error_does_not_raise_on_200():
    _raise_for_error(FakeResponse(200))  # istisna fırlatmamalı


def test_raise_for_error_418_message_mentions_ban_and_retry_after():
    response = FakeResponse(418, headers={"Retry-After": "120"}, json_data={"msg": "banned", "code": -1003})

    with pytest.raises(BinanceAPIError) as exc_info:
        _raise_for_error(response)

    assert "120" in str(exc_info.value)
    assert "engellendi" in str(exc_info.value)
    assert exc_info.value.code == -1003


def test_raise_for_error_429_message_is_clear_after_retries_exhausted():
    response = FakeResponse(429, json_data={"msg": "too many requests"})

    with pytest.raises(BinanceAPIError) as exc_info:
        _raise_for_error(response)

    assert "istek limiti" in str(exc_info.value)
