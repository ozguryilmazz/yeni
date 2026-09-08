from unittest.mock import patch

import pytest

from app.binance_client import (
    get_futures_kline_stats,
    get_futures_market_overview,
    get_futures_perpetual_symbols,
)
from app.repository import get_market_overview


def test_get_futures_perpetual_symbols_filters_to_usdt_perpetual_trading():
    exchange_info = {
        "symbols": [
            {"symbol": "BTCUSDT", "quoteAsset": "USDT", "contractType": "PERPETUAL", "status": "TRADING"},
            {
                "symbol": "BTCUSDT_240329",
                "quoteAsset": "USDT",
                "contractType": "CURRENT_QUARTER",
                "status": "TRADING",
            },
            {"symbol": "ETHBUSD", "quoteAsset": "BUSD", "contractType": "PERPETUAL", "status": "TRADING"},
            {"symbol": "OLDCOINUSDT", "quoteAsset": "USDT", "contractType": "PERPETUAL", "status": "BREAK"},
        ]
    }
    with patch("app.binance_client._public_get", return_value=exchange_info):
        symbols = get_futures_perpetual_symbols()

    assert symbols == ["BTCUSDT"]


def test_get_futures_kline_stats_parses_price_and_volume_change():
    # [openTime, open, high, low, close, volume, closeTime, quoteVolume, ...]
    previous = [1689996400000, "90", "95", "85", "100", "50", 1689999999999, "5000.0", 5, "25", "3000", "0"]
    current = [1690000000000, "100", "110", "90", "110", "100", 1690003600000, "12345.67", 10, "50", "6000", "0"]
    with patch("app.binance_client._public_get", return_value=[previous, current]):
        stats = get_futures_kline_stats("BTCUSDT", "1h")

    assert stats["last_price"] == 110.0
    assert stats["quote_volume"] == 12345.67
    assert stats["price_change_percent"] == pytest.approx(10.0)  # 100 -> 110 = %10
    assert stats["volume_change_percent"] == pytest.approx((12345.67 - 5000.0) / 5000.0 * 100)


def test_get_futures_kline_stats_uses_shared_client_when_given():
    previous = [0, "100", "100", "100", "100", "1", 0, "500.0", 1, "0", "0", "0"]
    current = [1, "100", "100", "100", "105", "1", 1, "999.0", 1, "0", "0", "0"]

    class FakeResponse:
        status_code = 200

        def json(self):
            return [previous, current]

    class FakeClient:
        def get(self, path, params=None):
            assert path == "/fapi/v1/klines"
            assert params["limit"] == 2
            return FakeResponse()

    stats = get_futures_kline_stats("BTCUSDT", "1h", client=FakeClient())
    assert stats["last_price"] == 105.0
    assert stats["quote_volume"] == 999.0
    assert stats["price_change_percent"] == pytest.approx(5.0)
    assert stats["volume_change_percent"] == pytest.approx((999.0 - 500.0) / 500.0 * 100)


def test_get_futures_kline_stats_single_candle_has_no_volume_change():
    kline = [[0, "100", "100", "100", "110", "1", 0, "999.0", 1, "0", "0", "0"]]
    with patch("app.binance_client._public_get", return_value=kline):
        stats = get_futures_kline_stats("BTCUSDT", "1h")

    assert stats["volume_change_percent"] == 0.0


def test_get_futures_kline_stats_empty_result_is_zero():
    with patch("app.binance_client._public_get", return_value=[]):
        stats = get_futures_kline_stats("BTCUSDT", "1h")

    assert stats == {
        "last_price": 0.0,
        "quote_volume": 0.0,
        "price_change_percent": 0.0,
        "volume_change_percent": 0.0,
    }


def test_market_overview_24h_uses_daily_klines_via_per_symbol_path():
    with (
        patch("app.binance_client.get_futures_perpetual_symbols", return_value=["BTCUSDT"]),
        patch(
            "app.binance_client.get_futures_kline_stats",
            side_effect=lambda symbol, interval, client=None: {
                "last_price": 100.0,
                "quote_volume": 500.5,
                "price_change_percent": 1.23,
                "volume_change_percent": 4.0,
            }
            if interval == "1d"
            else pytest.fail(f"unexpected interval {interval}"),
        ),
    ):
        overview = get_futures_market_overview("24h")

    assert overview == [
        {
            "symbol": "BTCUSDT",
            "last_price": 100.0,
            "quote_volume": 500.5,
            "price_change_percent": 1.23,
            "volume_change_percent": 4.0,
        }
    ]


def test_market_overview_1h_uses_per_symbol_klines():
    stats = {
        "BTCUSDT": {"last_price": 1.0, "quote_volume": 10.0, "price_change_percent": 1.0, "volume_change_percent": 0.0},
        "ETHUSDT": {"last_price": 2.0, "quote_volume": 20.0, "price_change_percent": -2.0, "volume_change_percent": 0.0},
    }
    with (
        patch("app.binance_client.get_futures_perpetual_symbols", return_value=list(stats)),
        patch(
            "app.binance_client.get_futures_kline_stats",
            side_effect=lambda symbol, interval, client=None: stats[symbol],
        ),
    ):
        overview = get_futures_market_overview("1h")

    assert {row["symbol"]: row["quote_volume"] for row in overview} == {
        symbol: s["quote_volume"] for symbol, s in stats.items()
    }


def test_market_overview_1h_skips_symbol_on_any_error():
    def fake_stats(symbol, interval, client=None):
        if symbol == "BROKENUSDT":
            raise RuntimeError("network kaboom")
        return {"quote_volume": 1.0, "price_change_percent": 0.0}

    with (
        patch("app.binance_client.get_futures_perpetual_symbols", return_value=["BTCUSDT", "BROKENUSDT"]),
        patch("app.binance_client.get_futures_kline_stats", side_effect=fake_stats),
    ):
        overview = get_futures_market_overview("1h")

    assert [row["symbol"] for row in overview] == ["BTCUSDT"]


def test_market_overview_invalid_period_raises():
    with patch("app.binance_client.get_futures_perpetual_symbols", return_value=["BTCUSDT"]):
        with pytest.raises(ValueError):
            get_futures_market_overview("1d")


def test_repository_get_market_overview_sorts_descending_by_volume():
    with patch(
        "app.repository.get_futures_market_overview",
        return_value=[
            {"symbol": "A", "quote_volume": 5.0, "price_change_percent": 0.0},
            {"symbol": "B", "quote_volume": 50.0, "price_change_percent": 0.0},
            {"symbol": "C", "quote_volume": 25.0, "price_change_percent": 0.0},
        ],
    ):
        result = get_market_overview("24h")

    assert [row["symbol"] for row in result] == ["B", "C", "A"]
