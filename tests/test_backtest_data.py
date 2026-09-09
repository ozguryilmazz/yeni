from app.binance_client import get_futures_historical_klines


class FakeResponse:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeClient:
    def __init__(self, pages: list[list[list]]):
        self._pages = pages
        self.calls: list[dict] = []

    def get(self, path, params=None):
        assert path == "/fapi/v1/klines"
        self.calls.append(params)
        page = self._pages[len(self.calls) - 1]
        return FakeResponse(page)


def _kline(open_time_ms: int) -> list:
    return [open_time_ms, "100", "101", "99", "100", "1", open_time_ms + 299_999, "100", 1, "0", "0", "0"]


def test_single_short_page_stops_after_one_request():
    page = [_kline(0), _kline(300_000)]
    client = FakeClient([page])

    result = get_futures_historical_klines("BTCUSDT", "5m", 0, 600_000, client=client)

    assert result == page
    assert len(client.calls) == 1
    assert client.calls[0]["startTime"] == 0


def test_paginates_when_a_full_page_is_returned():
    limit = 1500
    first_page = [_kline(i * 300_000) for i in range(limit)]
    second_page = [_kline((limit + i) * 300_000) for i in range(3)]
    client = FakeClient([first_page, second_page])

    result = get_futures_historical_klines("BTCUSDT", "5m", 0, (limit + 3) * 300_000, client=client)

    assert len(result) == limit + 3
    assert len(client.calls) == 2
    # İkinci istek, ilk sayfanın son mumunun açılış zamanı + interval'den başlamalı.
    expected_second_start = first_page[-1][0] + 300_000
    assert client.calls[1]["startTime"] == expected_second_start


def test_empty_first_page_returns_empty_list():
    client = FakeClient([[]])

    result = get_futures_historical_klines("BTCUSDT", "5m", 0, 600_000, client=client)

    assert result == []
    assert len(client.calls) == 1
