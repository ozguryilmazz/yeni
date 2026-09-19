import pytest

from app.backtest.indicators import atr, ema, rsi


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


def test_rsi_hand_calculated_example():
    # değişimler: +2, -1, +2 -> avg_gain=(2+0+2)/3=4/3, avg_loss=(0+1+0)/3=1/3
    # RS=4 -> RSI=100-100/(1+4)=80
    closes = [10.0, 12.0, 11.0, 13.0]

    result = rsi(closes, period=3)

    assert result[:3] == [None, None, None]
    assert result[3] == pytest.approx(80.0)


def test_rsi_monotonic_uptrend_is_100():
    closes = [float(i) for i in range(1, 20)]  # hep kazanç, hiç kayıp yok
    result = rsi(closes, period=14)

    assert all(v == pytest.approx(100.0) for v in result[14:])


def test_rsi_monotonic_downtrend_is_0():
    closes = [float(i) for i in range(20, 1, -1)]  # hep kayıp, hiç kazanç yok
    result = rsi(closes, period=14)

    assert all(v == pytest.approx(0.0) for v in result[14:])


def test_rsi_returns_all_none_when_not_enough_data():
    assert rsi([1.0, 2.0, 3.0], period=14) == [None, None, None]
