from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.backtest.engine import BacktestResult
from app.backtest.service import (
    WARMUP_CANDLES,
    BacktestComparison,
    run_backtest_comparison,
    run_backtest_for_symbol,
)
from app.binance_client import INTERVAL_MS_MAP


def _flat_klines(open_time_ms: int, count: int, interval_ms: int, price: str = "100") -> list[list]:
    return [
        [open_time_ms + i * interval_ms, price, price, price, price, "0", 0, "0", 0, "0", "0", "0"]
        for i in range(count)
    ]


def test_fetches_with_warmup_buffer_before_start_and_uppercases_symbol():
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    end = datetime(2024, 1, 3, tzinfo=timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    interval_ms = INTERVAL_MS_MAP["5m"]

    with patch(
        "app.backtest.service.get_futures_historical_klines", return_value=_flat_klines(0, 3, interval_ms)
    ) as mock_fetch:
        result = run_backtest_for_symbol("btcusdt", start, end)

    mock_fetch.assert_called_once()
    args, _ = mock_fetch.call_args
    assert args[0] == "BTCUSDT"
    assert args[1] == "5m"  # varsayılan zaman dilimi
    assert args[2] == start_ms - WARMUP_CANDLES * interval_ms
    assert args[3] == end_ms
    assert isinstance(result, BacktestResult)


def test_uses_selected_interval_for_klines_request_and_warmup_buffer():
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    end = datetime(2024, 1, 3, tzinfo=timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    interval_ms = INTERVAL_MS_MAP["1h"]

    with patch(
        "app.backtest.service.get_futures_historical_klines", return_value=_flat_klines(0, 3, interval_ms)
    ) as mock_fetch:
        run_backtest_for_symbol("BTCUSDT", start, end, interval="1h")

    args, _ = mock_fetch.call_args
    assert args[1] == "1h"
    assert args[2] == start_ms - WARMUP_CANDLES * interval_ms


def test_raises_when_start_is_not_before_end():
    same = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        run_backtest_for_symbol("BTCUSDT", same, same)


def test_raises_when_no_klines_returned():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 2, tzinfo=timezone.utc)
    with patch("app.backtest.service.get_futures_historical_klines", return_value=[]):
        with pytest.raises(ValueError):
            run_backtest_for_symbol("BTCUSDT", start, end)


def test_flat_price_data_produces_no_trades_and_unchanged_balance():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 1, tzinfo=timezone.utc)
    interval_ms = INTERVAL_MS_MAP["5m"]
    # ATR sabit fiyatta 0'a yakınsar -> giriş bandı sıfırlanır, hiç işlem açılmamalı.
    with patch(
        "app.backtest.service.get_futures_historical_klines", return_value=_flat_klines(0, 400, interval_ms)
    ):
        result = run_backtest_for_symbol("BTCUSDT", start, end)

    assert result.trades == []
    assert result.ending_balance_usd == pytest.approx(result.starting_balance_usd)


def test_comparison_fetches_klines_only_once_and_returns_all_three_variants():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 1, tzinfo=timezone.utc)
    interval_ms = INTERVAL_MS_MAP["5m"]

    with patch(
        "app.backtest.service.get_futures_historical_klines", return_value=_flat_klines(0, 400, interval_ms)
    ) as mock_fetch:
        comparison = run_backtest_comparison("BTCUSDT", start, end)

    mock_fetch.assert_called_once()  # veri tek seferde çekilip üç varyantta da tekrar kullanılmalı
    assert isinstance(comparison, BacktestComparison)
    assert isinstance(comparison.normal, BacktestResult)
    assert isinstance(comparison.reversed, BacktestResult)
    assert isinstance(comparison.neutral, BacktestResult)
    # Düz fiyatta ATR ~0 olduğundan üç varyantta da işlem açılmamalı.
    assert comparison.normal.trades == []
    assert comparison.reversed.trades == []
    assert comparison.neutral.trades == []


def test_comparison_raises_when_start_is_not_before_end():
    same = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        run_backtest_comparison("BTCUSDT", same, same)
