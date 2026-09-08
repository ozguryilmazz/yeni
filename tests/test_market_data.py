from unittest.mock import patch

import pytest

from app.binance_client import (
    get_futures_24h_tickers,
    get_futures_kline_quote_volume,
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


def test_get_futures_24h_tickers_returns_raw_list():
    with patch("app.binance_client._public_get", return_value=[{"symbol": "BTCUSDT", "quoteVolume": "123.0"}]):
        tickers = get_futures_24h_tickers()

    assert tickers == [{"symbol": "BTCUSDT", "quoteVolume": "123.0"}]


def test_get_futures_kline_quote_volume_parses_quote_asset_volume_field():
    kline = [[1690000000000, "1", "2", "0.5", "1.5", "100", 1690003600000, "12345.67", 10, "50", "6000", "0"]]
    with patch("app.binance_client._public_get", return_value=kline):
        volume = get_futures_kline_quote_volume("BTCUSDT", "1h")

    assert volume == 12345.67


def test_get_futures_kline_quote_volume_empty_result_is_zero():
    with patch("app.binance_client._public_get", return_value=[]):
        assert get_futures_kline_quote_volume("BTCUSDT", "1h") == 0.0


def test_market_overview_24h_filters_to_perpetual_symbols_only():
    with (
        patch("app.binance_client.get_futures_perpetual_symbols", return_value=["BTCUSDT"]),
        patch(
            "app.binance_client.get_futures_24h_tickers",
            return_value=[
                {"symbol": "BTCUSDT", "quoteVolume": "500.5"},
                {"symbol": "SOMEQUARTERLY", "quoteVolume": "999"},
            ],
        ),
    ):
        overview = get_futures_market_overview("24h")

    assert overview == [{"symbol": "BTCUSDT", "quote_volume": 500.5}]


def test_market_overview_1h_uses_per_symbol_klines():
    volumes = {"BTCUSDT": 10.0, "ETHUSDT": 20.0}
    with (
        patch("app.binance_client.get_futures_perpetual_symbols", return_value=list(volumes)),
        patch("app.binance_client.get_futures_kline_quote_volume", side_effect=lambda symbol, interval: volumes[symbol]),
    ):
        overview = get_futures_market_overview("1h")

    assert {row["symbol"]: row["quote_volume"] for row in overview} == volumes


def test_market_overview_invalid_period_raises():
    with patch("app.binance_client.get_futures_perpetual_symbols", return_value=["BTCUSDT"]):
        with pytest.raises(ValueError):
            get_futures_market_overview("1d")


def test_repository_get_market_overview_sorts_descending_by_volume():
    with patch(
        "app.repository.get_futures_market_overview",
        return_value=[
            {"symbol": "A", "quote_volume": 5.0},
            {"symbol": "B", "quote_volume": 50.0},
            {"symbol": "C", "quote_volume": 25.0},
        ],
    ):
        result = get_market_overview("24h")

    assert [row["symbol"] for row in result] == ["B", "C", "A"]
