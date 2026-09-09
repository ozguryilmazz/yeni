from unittest.mock import patch

import pytest

from app.backtest.engine import Candle, run_backtest

# Sabit test parametreleri: margin=2$, kaldıraç=5x -> notional=10$, quantity=0.1.
# fee_per_side = 10 * 0.0005 = 0.005 -> total_fee (giriş+çıkış) = 0.01.
# TP mesafesi (4x toplam komisyon) = 0.04 / 0.1 = 0.4 fiyat birimi.
# SL mesafesi (2x toplam komisyon) = 0.02 / 0.1 = 0.2 fiyat birimi.
TP_DISTANCE = 0.4
SL_DISTANCE = 0.2


def _run(candles, start_time_ms, ema_fast, ema_slow, ema_trend, atr_values, reverse=False):
    """İndikatör hesaplamalarını (app.backtest.indicators.ema/atr) sahte, elle
    kurgulanmış dizilerle değiştirerek pozisyon/TP/SL/komisyon mantığını
    indikatör matematiğinden bağımsız, deterministik şekilde test eder."""
    with (
        patch("app.backtest.engine.ema", side_effect=[ema_fast, ema_slow, ema_trend]),
        patch("app.backtest.engine.atr", return_value=atr_values),
    ):
        return run_backtest(candles, start_time_ms=start_time_ms, reverse=reverse)


def test_long_entry_and_take_profit_hit():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=101, low=100, close=100.2),
    ]
    # EMA9=EMA21=100 (bant: 99-101, close=100 içeride), EMA100=90 (close>trend -> LONG).
    # ATR yalnızca giriş bandını belirler; SL/TP artık komisyon maliyetinden hesaplanır.
    result = _run(candles, 0, [100, 100], [100, 100], [90, 90], [2, 2])

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
        Candle(open_time_ms=300_000, open=100, high=100.5, low=100, close=100.3),
    ]
    # EMA100=110 (close<trend -> SHORT) -> SL=entry+0.2, TP=entry-0.4 (bu mumda sadece SL vurulur).
    result = _run(candles, 0, [100, 100], [100, 100], [110, 110], [2, 2])

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
        Candle(open_time_ms=300_000, open=100, high=100.5, low=99.5, close=100),  # her ikisi de menzilde
    ]
    result = _run(candles, 0, [100, 100], [100, 100], [90, 90], [2, 2])

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "SL"
    assert result.trades[0].exit_price == pytest.approx(100 - SL_DISTANCE)


def test_forced_close_at_end_of_data_when_neither_tp_nor_sl_hit():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=100.1, low=99.85, close=100.05),
    ]
    result = _run(candles, 0, [100, 100], [100, 100], [90, 90], [2, 2])

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "EOD"
    assert trade.exit_price == pytest.approx(100.05)


def test_only_one_position_open_at_a_time():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),  # giriş
        Candle(open_time_ms=300_000, open=100, high=100.1, low=99.85, close=100),  # açık pozisyon, TP/SL yok
        Candle(open_time_ms=600_000, open=100, high=101, low=100, close=100.5),  # TP burada vurulur
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
    )

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "TP"


def test_candles_before_start_time_never_open_a_position():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),  # start'tan önce
    ]
    result = _run(candles, start_time_ms=300_000, ema_fast=[100], ema_slow=[100], ema_trend=[90], atr_values=[2])

    assert result.trades == []


def test_stops_opening_new_trades_once_balance_is_below_margin(monkeypatch):
    import app.backtest.engine as engine

    monkeypatch.setattr(engine, "STARTING_BALANCE_USD", 1.0)  # margin (2$) altında başlar
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    result = _run(candles, 0, [100], [100], [90], [2])

    assert result.trades == []
    assert result.stopped_early is True
    assert result.ending_balance_usd == pytest.approx(1.0)


def test_no_signal_outside_entry_band_or_when_atr_is_zero():
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    # Fiyat bandın çok dışında.
    result = _run(candles, 0, [80], [80], [90], [2])
    assert result.trades == []

    # ATR sıfır (band genişliği 0, işlem açılmamalı).
    result = _run(candles, 0, [100], [100], [90], [0])
    assert result.trades == []


def test_reverse_flips_long_to_short():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=100.1, low=99.9, close=100),
    ]
    # Normalde EMA100=90 (close>trend) -> LONG üretir; reverse=True ile SHORT açılmalı.
    result = _run(candles, 0, [100, 100], [100, 100], [90, 90], [2, 2], reverse=True)

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
    # Normalde EMA100=110 (close<trend) -> SHORT üretir; reverse=True ile LONG açılmalı.
    result = _run(candles, 0, [100, 100], [100, 100], [110, 110], [2, 2], reverse=True)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.side == "LONG"
    assert trade.stop_loss == pytest.approx(100 - SL_DISTANCE)
    assert trade.take_profit == pytest.approx(100 + TP_DISTANCE)


def test_sl_tp_distance_scales_with_taker_fee_not_atr():
    """SL/TP artık ATR'den bağımsızdır: farklı ATR değerleriyle bile aynı entry
    fiyatında aynı SL/TP mesafesi üretilmeli (yalnızca komisyona bağlı). ATR yalnızca
    giriş bandının genişliğini etkiler."""
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=100.1, low=99.9, close=100),
    ]

    result_low_atr = _run(candles, 0, [100, 100], [100, 100], [90, 90], [0.5, 0.5])
    result_high_atr = _run(candles, 0, [100, 100], [100, 100], [90, 90], [50, 50])

    assert result_low_atr.trades[0].stop_loss == pytest.approx(result_high_atr.trades[0].stop_loss)
    assert result_low_atr.trades[0].take_profit == pytest.approx(result_high_atr.trades[0].take_profit)
    assert result_low_atr.trades[0].stop_loss == pytest.approx(100 - SL_DISTANCE)
    assert result_low_atr.trades[0].take_profit == pytest.approx(100 + TP_DISTANCE)
