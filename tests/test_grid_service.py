from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.binance_client import INTERVAL_MS_MAP
from app.grid_trading.grid import GridBacktestResult
from app.grid_trading.service import compute_range_for_symbol, run_grid_backtest_for_symbol


def _klines(rows: list[tuple[float, float, float, float]], start_ms: int, interval_ms: int) -> list[list]:
    return [
        [start_ms + i * interval_ms, str(o), str(h), str(low), str(c), "0", 0, "0", 0, "0", "0", "0"]
        for i, (o, h, low, c) in enumerate(rows)
    ]


def _constant_atr_rows(n: int = 20) -> list[tuple[float, float, float, float]]:
    # bkz. test_backtest_indicators.test_atr_of_constant_range_settles_to_the_range:
    # high-low sabit 2, kapanış ortada sabit -> ATR(14) tam olarak 2.0'a oturur.
    return [(9.0, 10.0, 8.0, 9.0) for _ in range(n)]


def test_compute_range_for_symbol_fetches_lookback_window_and_uppercases_symbol():
    interval_ms = INTERVAL_MS_MAP["4h"]
    rows = _constant_atr_rows()

    with patch(
        "app.grid_trading.service.get_futures_historical_klines",
        return_value=_klines(rows, start_ms=0, interval_ms=interval_ms),
    ) as mock_fetch:
        with patch("app.grid_trading.service.time.time", return_value=0.0):
            result = compute_range_for_symbol("btcusdt", method="atr", interval="4h", lookback_candles=120, k=2.0)

    mock_fetch.assert_called_once()
    args, _ = mock_fetch.call_args
    assert args[0] == "BTCUSDT"
    assert args[1] == "4h"
    assert args[2] == -120 * interval_ms  # now_ms(0) - lookback*interval_ms
    assert args[3] == 0

    assert result.grid_range.method == "atr"
    assert result.grid_range.lower_price == pytest.approx(9.0 - 2 * 2.0)
    assert result.grid_range.upper_price == pytest.approx(9.0 + 2 * 2.0)
    assert len(result.candles) == len(rows)
    assert result.candles[-1].close == pytest.approx(9.0)


def test_compute_range_for_symbol_raises_when_no_klines_returned():
    with patch("app.grid_trading.service.get_futures_historical_klines", return_value=[]):
        with pytest.raises(ValueError):
            compute_range_for_symbol("BTCUSDT", method="atr")


def test_run_grid_backtest_for_symbol_fetches_requested_window_and_uppercases_symbol():
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    end = datetime(2024, 1, 3, tzinfo=timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    interval_ms = INTERVAL_MS_MAP["15m"]
    rows = [(100.0, 100.5, 99.5, 100.2)] * 50  # aralığa hiç değmeyen düz veri

    with patch(
        "app.grid_trading.service.get_futures_historical_klines",
        return_value=_klines(rows, start_ms=start_ms, interval_ms=interval_ms),
    ) as mock_fetch:
        result = run_grid_backtest_for_symbol(
            "btcusdt", start, end, interval="15m", lower_price=90.0, upper_price=110.0, grid_count=4, capital_usd=400.0
        )

    mock_fetch.assert_called_once()
    args, _ = mock_fetch.call_args
    assert args[0] == "BTCUSDT"
    assert args[1] == "15m"
    assert args[2] == start_ms
    assert args[3] == end_ms

    assert isinstance(result, GridBacktestResult)
    assert result.qty_per_grid == pytest.approx((400.0 / 4) / 100.0)
    assert result.trades == []  # fiyat hiçbir grid seviyesine değmedi


def test_run_grid_backtest_for_symbol_raises_when_start_is_not_before_end():
    same = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        run_grid_backtest_for_symbol("BTCUSDT", same, same, interval="15m", lower_price=90.0, upper_price=110.0)


def test_run_grid_backtest_for_symbol_raises_when_no_klines_returned():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 1, 2, tzinfo=timezone.utc)
    with patch("app.grid_trading.service.get_futures_historical_klines", return_value=[]):
        with pytest.raises(ValueError):
            run_grid_backtest_for_symbol("BTCUSDT", start, end, interval="15m", lower_price=90.0, upper_price=110.0)
