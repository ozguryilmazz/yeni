from unittest.mock import patch

import pytest

from app.backtest.engine import Candle
from app.strategies.liquidity_sweep_1m import (
    EQUAL_LEVEL_TOLERANCE_PCT,
    LOOKBACK_PERIOD,
    MAX_HOLDING_BARS,
    STRATEGY,
    _find_liquidity_level,
    _has_bearish_divergence,
    _has_bullish_divergence,
    compute_signals,
)


def test_strategy_registered_with_next_open_timing_and_max_holding_bars():
    assert STRATEGY.entry_timing == "next_open"
    assert STRATEGY.max_holding_bars == MAX_HOLDING_BARS
    assert STRATEGY.compute_signals is compute_signals


# ---- _find_liquidity_level ------------------------------------------------


def test_find_liquidity_level_returns_none_without_a_cluster():
    values = [80.0, 85.0, 90.0, 95.0, 99.0]  # birbirine yakın (tolerans içinde) hiçbiri yok
    assert _find_liquidity_level(values, EQUAL_LEVEL_TOLERANCE_PCT, "high") is None


def test_find_liquidity_level_finds_two_equal_highs():
    values = [80.0, 100.00, 90.0, 100.03, 70.0]  # 100.00 ve 100.03 birbirine %0.05 tolerans içinde
    assert _find_liquidity_level(values, EQUAL_LEVEL_TOLERANCE_PCT, "high") == pytest.approx(100.03)


def test_find_liquidity_level_picks_lowest_cluster_for_support():
    values = [20.00, 20.01, 50.0, 60.00, 60.02]  # iki küme; 'low' modunda en düşük kümenin min'i
    assert _find_liquidity_level(values, EQUAL_LEVEL_TOLERANCE_PCT, "low") == pytest.approx(20.00)


# ---- diverjans -------------------------------------------------------------


def test_bearish_divergence_detected_on_higher_high_lower_rsi():
    highs_window = [100.0, 105.0, 102.0]  # tepe RSI index1'de (105)
    rsi_window = [50.0, 80.0, 60.0]
    assert _has_bearish_divergence(highs_window, rsi_window, current_high=110.0, current_rsi=70.0) is True


def test_bearish_divergence_false_when_rsi_also_makes_higher_high():
    highs_window = [100.0, 105.0]
    rsi_window = [50.0, 60.0]
    assert _has_bearish_divergence(highs_window, rsi_window, current_high=110.0, current_rsi=70.0) is False


def test_bullish_divergence_detected_on_lower_low_higher_rsi():
    lows_window = [50.0, 40.0, 45.0]  # dip RSI index1'de (en düşük RSI)
    rsi_window = [50.0, 20.0, 40.0]
    assert _has_bullish_divergence(lows_window, rsi_window, current_low=35.0, current_rsi=30.0) is True


# ---- compute_signals (uçtan uca) -------------------------------------------


def _flat_lookback_candles(count: int, base: float = 80.0) -> list[Candle]:
    """LOOKBACK_PERIOD kadar, birbirine yakın olmayan (kümelenmeyen) OHLC
    mumları üretir — testlerde kasıtlı eşit tepe/dip eklenmeden önceki temel."""
    candles = []
    for j in range(count):
        high = base + j
        low = high - 2.0
        close = high - 1.0
        candles.append(
            Candle(open_time_ms=j * 60_000, open=close, high=high, low=low, close=close, volume=100.0)
        )
    return candles


def test_short_signal_on_swept_resistance_with_overbought_rsi():
    candles = _flat_lookback_candles(LOOKBACK_PERIOD)
    candles[5].high = 100.00  # eşit tepe kümesi
    candles[10].high = 100.03
    # sweep + red: high seviyeyi aşıyor, close altına kapanıyor; hacim 2x ortalama.
    candles.append(
        Candle(open_time_ms=LOOKBACK_PERIOD * 60_000, open=99.8, high=100.1, low=99.4, close=99.5, volume=200.0)
    )
    rsi_values = [50.0] * LOOKBACK_PERIOD + [70.0]  # son mumda RSI aşırı alım (>65)

    with patch("app.strategies.liquidity_sweep_1m.rsi", return_value=rsi_values):
        signals = compute_signals(candles)

    assert signals[LOOKBACK_PERIOD] == "SHORT"


def test_long_signal_on_swept_support_with_oversold_rsi():
    candles = _flat_lookback_candles(LOOKBACK_PERIOD, base=80.0)
    # Doğal aralığın (80-99) dışında, birbirine yakın bir eşit dip kümesi:
    candles[5] = Candle(open_time_ms=5 * 60_000, open=25.7, high=26.0, low=25.50, close=25.8, volume=100.0)
    candles[10] = Candle(open_time_ms=10 * 60_000, open=25.7, high=26.0, low=25.51, close=25.8, volume=100.0)
    candles.append(
        Candle(open_time_ms=LOOKBACK_PERIOD * 60_000, open=25.4, high=25.7, low=25.3, close=25.6, volume=200.0)
    )
    rsi_values = [50.0] * LOOKBACK_PERIOD + [30.0]  # son mumda RSI aşırı satım (<35)

    with patch("app.strategies.liquidity_sweep_1m.rsi", return_value=rsi_values):
        signals = compute_signals(candles)

    assert signals[LOOKBACK_PERIOD] == "LONG"


def test_no_signal_without_volume_spike():
    candles = _flat_lookback_candles(LOOKBACK_PERIOD)
    candles[5].high = 100.00
    candles[10].high = 100.03
    # Hacim sıçraması YOK (ortalamayla aynı) -> sweep+red olsa bile sinyal olmamalı.
    candles.append(
        Candle(open_time_ms=LOOKBACK_PERIOD * 60_000, open=99.8, high=100.1, low=99.4, close=99.5, volume=100.0)
    )
    rsi_values = [50.0] * LOOKBACK_PERIOD + [70.0]

    with patch("app.strategies.liquidity_sweep_1m.rsi", return_value=rsi_values):
        signals = compute_signals(candles)

    assert signals[LOOKBACK_PERIOD] is None


def test_no_signal_without_rejection_close():
    candles = _flat_lookback_candles(LOOKBACK_PERIOD)
    candles[5].high = 100.00
    candles[10].high = 100.03
    # Sweep var ama kapanış seviyenin ÜSTÜNDE (red yok).
    candles.append(
        Candle(open_time_ms=LOOKBACK_PERIOD * 60_000, open=99.8, high=100.2, low=99.9, close=100.15, volume=200.0)
    )
    rsi_values = [50.0] * LOOKBACK_PERIOD + [70.0]

    with patch("app.strategies.liquidity_sweep_1m.rsi", return_value=rsi_values):
        signals = compute_signals(candles)

    assert signals[LOOKBACK_PERIOD] is None
