from unittest.mock import patch

import pytest

from app.backtest.engine import Candle
from app.strategies.scalp_5d import STRATEGY, TREND_SLOPE_LOOKBACK, _compute_trend_slope, compute_signals

STRONG_UPTREND_SLOPE = 100.0
STRONG_DOWNTREND_SLOPE = -100.0


def _signals(candles, ema_fast, ema_slow, ema_trend, atr_values, trend_slope):
    """EMA/ATR/eğim hesaplamalarını sahte, elle kurgulanmış dizilerle
    değiştirerek sinyal mantığını indikatör matematiğinden bağımsız,
    deterministik şekilde test eder."""
    with (
        patch("app.strategies.scalp_5d.ema", side_effect=[ema_fast, ema_slow, ema_trend]),
        patch("app.strategies.scalp_5d.atr", return_value=atr_values),
        patch("app.strategies.scalp_5d._compute_trend_slope", return_value=trend_slope),
    ):
        return compute_signals(candles)


def test_strategy_is_registered_with_a_name_and_warmup():
    assert STRATEGY.name
    assert STRATEGY.compute_signals is compute_signals
    assert STRATEGY.warmup_candles > 0


def test_long_signal_when_price_above_rising_trend_and_inside_band():
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    signals = _signals(
        candles, [100], [100], [90], [2], [STRONG_UPTREND_SLOPE]
    )

    assert signals == ["LONG"]


def test_short_signal_when_price_below_falling_trend_and_inside_band():
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    signals = _signals(
        candles, [100], [100], [110], [2], [STRONG_DOWNTREND_SLOPE]
    )

    assert signals == ["SHORT"]


def test_no_signal_outside_entry_band():
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    signals = _signals(candles, [80], [80], [90], [2], [STRONG_UPTREND_SLOPE])

    assert signals == [None]


def test_no_signal_when_atr_is_zero():
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    signals = _signals(candles, [100], [100], [90], [0], [STRONG_UPTREND_SLOPE])

    assert signals == [None]


def test_no_signal_when_trend_is_flat_even_if_price_is_on_the_right_side():
    """Fiyat EMA100'ün üstünde olsa bile EMA100'ün kendisi yatay (chop) ise
    sinyal üretilmemeli — trend eğim filtresinin asıl amacı budur."""
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    signals = _signals(candles, [100], [100], [90], [2], [0.0])  # eğim sıfır -> chop

    assert signals == [None]


def test_no_signal_when_any_indicator_not_yet_warmed_up():
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    signals = _signals(candles, [None], [100], [90], [2], [STRONG_UPTREND_SLOPE])

    assert signals == [None]


def test_compute_trend_slope_measures_change_over_lookback_window():
    ema_trend = [100.0] * (TREND_SLOPE_LOOKBACK + 5)
    ema_trend[-1] = 130.0  # son mumda EMA100 30 birim yükselmiş

    slope = _compute_trend_slope(ema_trend)

    assert slope[:TREND_SLOPE_LOOKBACK] == [None] * TREND_SLOPE_LOOKBACK
    assert slope[TREND_SLOPE_LOOKBACK] == pytest.approx(0.0)  # 100 - 100
    assert slope[-1] == pytest.approx(30.0)  # 130 - 100


def test_compute_trend_slope_none_when_either_end_missing():
    ema_trend = [None, None, 100.0, 105.0]

    slope = _compute_trend_slope(ema_trend)

    assert slope == [None, None, None, None]  # n=4 < TREND_SLOPE_LOOKBACK, hiçbiri hesaplanamaz
