import pytest

from app.backtest.indicators import atr, ema


def test_ema_seeds_with_sma_then_smooths():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = ema(values, period=3)

    assert result[0] is None
    assert result[1] is None
    assert result[2] == pytest.approx(2.0)  # SMA(1,2,3)
    assert result[3] == pytest.approx(3.0)  # 4*0.5 + 2*0.5
    assert result[4] == pytest.approx(4.0)  # 5*0.5 + 3*0.5


def test_ema_of_constant_series_equals_the_constant():
    values = [5.0] * 10
    result = ema(values, period=3)

    assert all(v == pytest.approx(5.0) for v in result[2:])


def test_ema_returns_all_none_when_not_enough_data():
    assert ema([1.0, 2.0], period=5) == [None, None]


def test_ema_rejects_non_positive_period():
    with pytest.raises(ValueError):
        ema([1.0, 2.0, 3.0], period=0)


def test_atr_of_constant_range_settles_to_the_range():
    # high-low sabit 2, kapanış aralığın ortasında sabit -> her True Range = 2.
    highs = [10.0] * 20
    lows = [8.0] * 20
    closes = [9.0] * 20

    result = atr(highs, lows, closes, period=14)

    assert result[:14] == [None] * 14
    assert all(v == pytest.approx(2.0) for v in result[14:])


def test_atr_reacts_to_a_volatility_spike():
    highs = [10.0] * 16
    lows = [8.0] * 16
    closes = [9.0] * 16
    # 15. mumda (index 15) ani bir genişleme.
    highs[15] = 20.0
    lows[15] = 8.0

    result = atr(highs, lows, closes, period=14)

    assert result[14] == pytest.approx(2.0)
    # Wilder smoothing: prev*(period-1)/period + TR/period
    expected_15 = (2.0 * 13 + 12.0) / 14
    assert result[15] == pytest.approx(expected_15)


def test_atr_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        atr([1.0, 2.0], [1.0], [1.0, 2.0])
