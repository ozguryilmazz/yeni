import pytest

from app.backtest.engine import Candle, run_backtest
from app.position_sizing import NEUTRAL_FEE_MULT

# margin=2$, kaldıraç=5x -> notional=10$, quantity=0.1 (bkz. test_position_sizing.py).
# TP mesafesi (20x toplam komisyon) = 2.0 fiyat birimi, SL mesafesi (10x) = 1.0.
TP_DISTANCE = 2.0
SL_DISTANCE = 1.0


def _fixed_signals(*signals: str | None):
    """Testlerde gerçek bir strateji yerine sabit, elle kurgulanmış bir sinyal
    dizisi döndüren sahte 'compute_signals' fonksiyonu — pozisyon/TP/SL/
    komisyon mantığını strateji sinyal üretiminden bağımsız test eder."""

    def compute_signals(candles):
        return list(signals)

    return compute_signals


def test_long_entry_and_take_profit_hit():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=103, low=100.5, close=102.5),
    ]
    result = run_backtest(candles, 0, _fixed_signals("LONG", None))

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
    result = run_backtest(candles, 0, _fixed_signals("SHORT", None))

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
    result = run_backtest(candles, 0, _fixed_signals("LONG", None))

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "SL"
    assert result.trades[0].exit_price == pytest.approx(100 - SL_DISTANCE)


def test_forced_close_at_end_of_data_when_neither_tp_nor_sl_hit():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=101, low=99.5, close=100.5),
    ]
    result = run_backtest(candles, 0, _fixed_signals("LONG", None))

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
    # index1'de de sinyal olsa bile (pozisyon açıkken), yeni giriş aranmamalı -> tek işlem.
    result = run_backtest(candles, 0, _fixed_signals("LONG", "LONG", None))

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "TP"


def test_candles_before_start_time_never_open_a_position():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),  # start'tan önce
    ]
    result = run_backtest(candles, start_time_ms=300_000, compute_signals=_fixed_signals("LONG"))

    assert result.trades == []


def test_none_signal_never_opens_a_position():
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    result = run_backtest(candles, 0, _fixed_signals(None))

    assert result.trades == []


def test_stops_opening_new_trades_once_balance_is_below_margin(monkeypatch):
    import app.backtest.engine as engine

    monkeypatch.setattr(engine, "STARTING_BALANCE_USD", 1.0)  # margin (2$) altında başlar
    candles = [Candle(open_time_ms=0, open=100, high=100, low=100, close=100)]

    result = run_backtest(candles, 0, _fixed_signals("LONG"))

    assert result.trades == []
    assert result.stopped_early is True
    assert result.ending_balance_usd == pytest.approx(1.0)


def test_reverse_flips_long_to_short():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=100.1, low=99.9, close=100),
    ]
    result = run_backtest(candles, 0, _fixed_signals("LONG", None), reverse=True)

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
    result = run_backtest(candles, 0, _fixed_signals("SHORT", None), reverse=True)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.side == "LONG"
    assert trade.stop_loss == pytest.approx(100 - SL_DISTANCE)
    assert trade.take_profit == pytest.approx(100 + TP_DISTANCE)


def test_neutral_fee_mult_produces_symmetric_sl_tp_distance():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=100.1, low=99.9, close=100),
    ]
    result = run_backtest(
        candles,
        0,
        _fixed_signals("LONG", None),
        sl_fee_mult=NEUTRAL_FEE_MULT,
        tp_fee_mult=NEUTRAL_FEE_MULT,
    )

    trade = result.trades[0]
    sl_distance = trade.entry_price - trade.stop_loss
    tp_distance = trade.take_profit - trade.entry_price
    assert sl_distance == pytest.approx(tp_distance)


def test_custom_margin_and_leverage_change_quantity():
    candles = [
        Candle(open_time_ms=0, open=100, high=100, low=100, close=100),
        Candle(open_time_ms=300_000, open=100, high=100.1, low=99.9, close=100),
    ]
    result = run_backtest(candles, 0, _fixed_signals("LONG", None), margin_usd=4.0, leverage=10)

    assert result.trades[0].quantity == pytest.approx(0.4)  # (4$ * 10x) / 100
