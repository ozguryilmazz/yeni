import math

import pytest

from app.backtest.engine import Candle
from app.grid_trading.range_methods import (
    atr_range,
    bollinger_range,
    compute_range,
    support_resistance_range,
)


def _candle(high: float, low: float, close: float, i: int = 0) -> Candle:
    return Candle(open_time_ms=i * 60_000, open=close, high=high, low=low, close=close)


def _support_resistance_candles(cycles: int = 4) -> list[Candle]:
    # Her çevrimde: A mumu desteği (low=100) TAM AYNI değerle tekrarlar ama
    # high'ı her seferinde biraz farklıdır (kümelenmez); B mumu direnci
    # (high=110) TAM AYNI değerle tekrarlar ama low'u her seferinde biraz
    # farklıdır -- yani 100 ve 110 dışında hiçbir seviye >=2 dokunuş almaz.
    candles = []
    i = 0
    for cycle in range(cycles):
        candles.append(_candle(high=105 + cycle, low=100, close=102, i=i))
        i += 1
        candles.append(_candle(high=110, low=105 + cycle, close=108, i=i))
        i += 1
    return candles


def test_support_resistance_range_picks_most_touched_clusters():
    candles = _support_resistance_candles(cycles=4)

    result = support_resistance_range(candles, min_touches=2, tolerance_pct=0.005, margin_pct=0.015)

    assert result.method == "support_resistance"
    assert result.details["resistance_level"] == pytest.approx(110.0)
    assert result.details["resistance_touches"] == 4
    assert result.details["support_level"] == pytest.approx(100.0)
    assert result.details["support_touches"] == 4
    assert result.details["resistance_fallback"] is False
    assert result.details["support_fallback"] is False
    assert result.upper_price == pytest.approx(110.0 * 1.015)
    assert result.lower_price == pytest.approx(100.0 * 0.985)


def test_support_resistance_range_falls_back_when_no_level_is_retested():
    # Her mum kesinlikle farklı bir yüksek/düşük yapıyor -> hiçbir küme
    # min_touches'a ulaşamıyor -> ham pencere max/min'ine düşülmeli.
    candles = [_candle(high=100.0 + i, low=90.0 - i, close=95.0, i=i) for i in range(10)]

    result = support_resistance_range(candles, min_touches=2)

    assert result.details["resistance_fallback"] is True
    assert result.details["support_fallback"] is True
    assert result.details["resistance_level"] == pytest.approx(109.0)  # max high
    assert result.details["support_level"] == pytest.approx(81.0)  # min low


def test_support_resistance_range_requires_candles():
    with pytest.raises(ValueError):
        support_resistance_range([])


def test_bollinger_range_matches_hand_calculated_bands():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    candles = [_candle(high=c, low=c, close=c, i=i) for i, c in enumerate(closes)]

    result = bollinger_range(candles, period=3, std_mult=2.0)

    std = math.sqrt(2 / 3)  # pencere [3,4,5]: ortalama 4, popülasyon varyansı 2/3
    assert result.method == "bollinger"
    assert result.details["middle"] == pytest.approx(4.0)
    assert result.upper_price == pytest.approx(4.0 + 2 * std)
    assert result.lower_price == pytest.approx(4.0 - 2 * std)


def test_bollinger_range_requires_enough_candles():
    candles = [_candle(high=1.0, low=1.0, close=1.0, i=i) for i in range(5)]
    with pytest.raises(ValueError):
        bollinger_range(candles, period=20)


def test_atr_range_uses_current_price_plus_minus_k_times_atr():
    n = 20
    candles = [_candle(high=10.0, low=8.0, close=9.0, i=i) for i in range(n)]

    result = atr_range(candles, k=3.0, period=14)

    # test_atr_of_constant_range_settles_to_the_range (bkz. test_backtest_indicators.py) ile
    # aynı kurulum: sabit aralık -> ATR(14) tam olarak 2.0'a oturur.
    assert result.details["atr"] == pytest.approx(2.0)
    assert result.details["current_price"] == pytest.approx(9.0)
    assert result.lower_price == pytest.approx(9.0 - 3 * 2.0)
    assert result.upper_price == pytest.approx(9.0 + 3 * 2.0)


def test_atr_range_requires_enough_candles():
    candles = [_candle(high=10.0, low=8.0, close=9.0, i=i) for i in range(5)]
    with pytest.raises(ValueError):
        atr_range(candles, period=14)


def test_compute_range_dispatches_by_method_name():
    n = 20
    candles = [_candle(high=10.0, low=8.0, close=9.0, i=i) for i in range(n)]

    result = compute_range("atr", candles, k=2.0, period=14)

    assert result.method == "atr"
    assert result.lower_price == pytest.approx(9.0 - 2 * 2.0)


def test_compute_range_rejects_unknown_method():
    with pytest.raises(ValueError):
        compute_range("unknown", [])
