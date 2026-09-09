from unittest.mock import patch

import pytest

from app.backtest.engine import NEUTRAL_FEE_MULT, TREND_SLOPE_LOOKBACK, Candle, _compute_trend_slope, run_backtest

# Sabit test parametreleri: margin=2$, kaldıraç=5x -> notional=10$, quantity=0.1.
# fee_per_side = 10 * 0.0005 = 0.005 -> total_fee (giriş+çıkış) = 0.01.
# TP mesafesi (20x toplam komisyon) = 0.2 / 0.1 = 2.0 fiyat birimi.
# SL mesafesi (10x toplam komisyon) = 0.1 / 0.1 = 1.0 fiyat birimi.
TP_DISTANCE = 2.0
SL_DISTANCE = 1.0

# Testlerde kullanılan ATR'lerin (en fazla 50) hepsinde min_slope = 0.5*ATR <= 25
# kalır; 100 bu eşiği her durumda rahatça aşar (uptrend), -100 ise downtrend için.
STRONG_UPTREND_SLOPE = 100.0
STRONG_DOWNTREND_SLOPE = -100.0


def _run(
    candles,
    start_time_ms,
    ema_fast,
    ema_slow,
    ema_trend,
    atr_values,
    trend_slope,
    reverse=False,
    sl_fee_mult=None,
    tp_fee_mult=None,
):
    """İndikatör hesaplamalarını (app.backtest.indicators.ema/atr) ve eğim
    hesabını (app.backtest.engine._compute_trend_slope) sahte, elle kurgulanmış
    dizilerle değiştirerek pozisyon/TP/SL/komisyon mantığını indikatör
    matematiğinden bağımsız, deterministik şekilde test eder."""
    kwargs = {}
    if sl_fee_mult is not None:
        kwargs["sl_fee_mult"] = sl_fee_mult
    if tp_fee_mult is not None:
        kwargs["tp_fee_mult"] = tp_fee_mult
    with (
        patch("app.backtest.engine.ema", side_effect=[ema_fast, ema_slow, ema_trend]),
        patch("app.backtest.engine.atr", return_value=atr_values),
        patch("app.backtest.engine._compute_trend_slope", return_value=trend_slope),
    ):
        return run_backtest(candles, start_time_ms=start_time_ms, reverse=reverse, **kwargs)


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


def test_long_entry_and_take_profit_hit():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=103, low=100.5, close=102.5),
    ]
    # EMA9=EMA21=100 (bant: 99-101, close=100 içeride), EMA100=90 (close>trend -> LONG),
    # EMA100 güçlü şekilde yükseliyor (uptrend teyidi).
    # ATR yalnızca giriş bandını belirler; SL/TP artık komisyon maliyetinden hesaplanır.
    result = _run(
        candles, 0, [100, 100], [100, 100], [90, 90], [2, 2], [STRONG_UPTREND_SLOPE, STRONG_UPTREND_SLOPE]
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.side == "LONG"
    assert trade.entry_price == pytest.approx(100)
    assert trade.stop_loss == pytest.approx(100 - SL_DISTANCE)
    assert trade.take_profit == pytest.approx(100 + TP_DISTANCE)
    assert trade.quantity == pytest.approx(0.1)  # (2$ * 5x) / 100
    assert trade.exit_reason == "TP"
    assert trade.exit_price == pytest.approx(100 + TP_DISTANCE)

    exit_price = 100 + TP_DISTANCE
    gross_pnl = (exit_price - 100) * 0.1
    fees = 100 * 0.1 * 0.0005 + exit_price * 0.1 * 0.0005
    assert trade.gross_pnl_usd == pytest.approx(gross_pnl)
    assert trade.fees_usd == pytest.approx(fees)
    assert trade.net_pnl_usd == pytest.approx(gross_pnl - fees)
    assert result.ending_balance_usd == pytest.approx(100 + gross_pnl - fees)


def test_short_entry_and_stop_loss_hit():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=101.5, low=99.5, close=100.5),
    ]
    # EMA100=110 (close<trend -> SHORT), EMA100 güçlü şekilde düşüyor (downtrend teyidi)
    # -> SL=entry+1.0, TP=entry-2.0 (bu mumda sadece SL vurulur).
    result = _run(
        candles, 0, [100, 100], [100, 100], [110, 110], [2, 2], [STRONG_DOWNTREND_SLOPE, STRONG_DOWNTREND_SLOPE]
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.side == "SHORT"
    assert trade.stop_loss == pytest.approx(100 + SL_DISTANCE)
    assert trade.take_profit == pytest.approx(100 - TP_DISTANCE)
    assert trade.exit_reason == "SL"
    assert trade.exit_price == pytest.approx(100 + SL_DISTANCE)
    assert trade.net_pnl_usd < 0


def test_same_candle_tp_and_sl_band_prefers_stop_loss():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=103, low=98, close=100),  # her ikisi de menzilde
    ]
    result = _run(
        candles, 0, [100, 100], [100, 100], [90, 90], [2, 2], [STRONG_UPTREND_SLOPE, STRONG_UPTREND_SLOPE]
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "SL"
    assert result.trades[0].exit_price == pytest.approx(100 - SL_DISTANCE)


def test_forced_close_at_end_of_data_when_neither_tp_nor_sl_hit():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=101, low=99.5, close=100.5),
    ]
    result = _run(
        candles, 0, [100, 100], [100, 100], [90, 90], [2, 2], [STRONG_UPTREND_SLOPE, STRONG_UPTREND_SLOPE]
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "EOD"
    assert trade.exit_price == pytest.approx(100.5)


def test_only_one_position_open_at_a_time():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),  # giriş
        Candle(open_time_ms=300_000, open=100, high=101, low=99.5, close=100),  # açık pozisyon, TP/SL yok
        Candle(open_time_ms=600_000, open=100, high=103, low=100, close=102.5),  # TP burada vurulur
    ]
    # Her mumda sinyal koşulları teknik olarak sağlansa da (index1 dahil), pozisyon
    # açıkken yeni giriş aranmamalı -> toplam tek işlem olmalı.
    result = _run(
        candles,
        0,
        [100, 100, 100],
        [100, 100, 100],
        [90, 90, 90],
        [2, 2, 2],
        [STRONG_UPTREND_SLOPE, STRONG_UPTREND_SLOPE, STRONG_UPTREND_SLOPE],
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "TP"


def test_candles_before_start_time_never_open_a_position():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),  # start'tan önce
    ]
    result = _run(
        candles,
        start_time_ms=300_000,
        ema_fast=[100],
        ema_slow=[100],
        ema_trend=[90],
        atr_values=[2],
        trend_slope=[STRONG_UPTREND_SLOPE],
    )

    assert result.trades == []


def test_stops_opening_new_trades_once_balance_is_below_margin(monkeypatch):
    import app.backtest.engine as engine

    monkeypatch.setattr(engine, "STARTING_BALANCE_USD", 1.0)  # margin (2$) altında başlar
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    result = _run(candles, 0, [100], [100], [90], [2], [STRONG_UPTREND_SLOPE])

    assert result.trades == []
    assert result.stopped_early is True
    assert result.ending_balance_usd == pytest.approx(1.0)


def test_no_signal_outside_entry_band_or_when_atr_is_zero():
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    # Fiyat bandın çok dışında.
    result = _run(candles, 0, [80], [80], [90], [2], [STRONG_UPTREND_SLOPE])
    assert result.trades == []

    # ATR sıfır (band genişliği 0, işlem açılmamalı).
    result = _run(candles, 0, [100], [100], [90], [0], [STRONG_UPTREND_SLOPE])
    assert result.trades == []


def test_no_signal_when_trend_is_flat_even_if_price_is_on_the_right_side():
    """Fiyat EMA100'ün üstünde olsa bile EMA100'ün kendisi yatay (chop) ise
    işlem açılmamalı — trend eğim filtresinin asıl amacı budur."""
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    result = _run(candles, 0, [100], [100], [90], [2], [0.0])  # eğim sıfır -> chop

    assert result.trades == []


def test_reverse_flips_long_to_short():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=100.1, low=99.9, close=100),
    ]
    # Normalde EMA100=90 + yükselen eğim -> LONG üretir; reverse=True ile SHORT açılmalı.
    result = _run(
        candles,
        0,
        [100, 100],
        [100, 100],
        [90, 90],
        [2, 2],
        [STRONG_UPTREND_SLOPE, STRONG_UPTREND_SLOPE],
        reverse=True,
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.side == "SHORT"
    assert trade.stop_loss == pytest.approx(100 + SL_DISTANCE)
    assert trade.take_profit == pytest.approx(100 - TP_DISTANCE)


def test_reverse_flips_short_to_long():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=100.1, low=99.9, close=100),
    ]
    # Normalde EMA100=110 + düşen eğim -> SHORT üretir; reverse=True ile LONG açılmalı.
    result = _run(
        candles,
        0,
        [100, 100],
        [100, 100],
        [110, 110],
        [2, 2],
        [STRONG_DOWNTREND_SLOPE, STRONG_DOWNTREND_SLOPE],
        reverse=True,
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.side == "LONG"
    assert trade.stop_loss == pytest.approx(100 - SL_DISTANCE)
    assert trade.take_profit == pytest.approx(100 + TP_DISTANCE)


def test_sl_tp_distance_scales_with_taker_fee_not_atr():
    """SL/TP artık ATR'den bağımsızdır: farklı ATR değerleriyle bile aynı entry
    fiyatında aynı SL/TP mesafesi üretilmeli (yalnızca komisyona bağlı). ATR yalnızca
    giriş bandının genişliğini ve eğim eşiğini etkiler."""
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=100.1, low=99.9, close=100),
    ]

    result_low_atr = _run(
        candles, 0, [100, 100], [100, 100], [90, 90], [0.5, 0.5], [STRONG_UPTREND_SLOPE, STRONG_UPTREND_SLOPE]
    )
    result_high_atr = _run(
        candles, 0, [100, 100], [100, 100], [90, 90], [50, 50], [STRONG_UPTREND_SLOPE, STRONG_UPTREND_SLOPE]
    )

    assert result_low_atr.trades[0].stop_loss == pytest.approx(result_high_atr.trades[0].stop_loss)
    assert result_low_atr.trades[0].take_profit == pytest.approx(result_high_atr.trades[0].take_profit)
    assert result_low_atr.trades[0].stop_loss == pytest.approx(100 - SL_DISTANCE)
    assert result_low_atr.trades[0].take_profit == pytest.approx(100 + TP_DISTANCE)


def test_neutral_fee_mult_produces_symmetric_sl_tp_distance():
    """NEUTRAL_FEE_MULT (SL=TP) ile çağrıldığında, giriş her iki yönden de aynı
    mesafede simetrik SL/TP üretmeli — 'nötr' karşılaştırmanın dayandığı temel."""
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=100.1, low=99.9, close=100),
    ]
    result = _run(
        candles,
        0,
        [100, 100],
        [100, 100],
        [90, 90],
        [2, 2],
        [STRONG_UPTREND_SLOPE, STRONG_UPTREND_SLOPE],
        sl_fee_mult=NEUTRAL_FEE_MULT,
        tp_fee_mult=NEUTRAL_FEE_MULT,
    )

    trade = result.trades[0]
    sl_distance = trade.entry_price - trade.stop_loss
    tp_distance = trade.take_profit - trade.entry_price
    assert sl_distance == pytest.approx(tp_distance)
