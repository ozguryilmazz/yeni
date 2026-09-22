from unittest.mock import patch

import pytest

from app.backtest.engine import Candle
from app.live_trading.engine import LiveTradingEngine, RiskParams
from app.strategies.base import Strategy

SYMBOL_INFO = {
    "symbol": "BTCUSDT",
    "filters": [
        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
        {"filterType": "PRICE_FILTER", "tickSize": "0.10", "minPrice": "0"},
    ],
}


def _always_long(candles):
    return ["LONG"] * len(candles)


def _always_none(candles):
    return [None] * len(candles)


def _fixed_strategy(compute_signals, warmup=1, max_holding_bars=None):
    return Strategy(
        name="test", compute_signals=compute_signals, warmup_candles=warmup, max_holding_bars=max_holding_bars
    )


def _make_engine(mode="auto", compute_signals=_always_long, on_error=None, max_holding_bars=None):
    calls = {
        "status": [],
        "signal": [],
        "confirmation": [],
        "order_placed": [],
        "position_closed": [],
        "error": [],
    }
    engine = LiveTradingEngine(
        api_key="key",
        api_secret="secret",
        symbol="btcusdt",
        interval="5m",
        strategy=_fixed_strategy(compute_signals, max_holding_bars=max_holding_bars),
        risk=RiskParams(margin_usd=2.0, leverage=5, sl_fee_mult=10.0, tp_fee_mult=20.0),
        mode=mode,
        on_status=lambda msg: calls["status"].append(msg),
        on_signal=lambda side, price: calls["signal"].append((side, price)),
        on_confirmation_needed=lambda *args: calls["confirmation"].append(args),
        on_order_placed=lambda trade: calls["order_placed"].append(trade),
        on_position_closed=lambda reason: calls["position_closed"].append(reason),
        on_error=(on_error or (lambda msg: calls["error"].append(msg))),
    )
    engine._symbol_info = SYMBOL_INFO
    return engine, calls


def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        LiveTradingEngine(
            api_key="k", api_secret="s", symbol="BTCUSDT", interval="5m",
            strategy=_fixed_strategy(_always_none), risk=RiskParams(2.0, 5, 10.0, 20.0), mode="yolo",
            on_status=lambda m: None, on_signal=lambda *a: None, on_confirmation_needed=lambda *a: None,
            on_order_placed=lambda t: None, on_position_closed=lambda r: None, on_error=lambda m: None,
        )


def test_none_signal_does_not_place_order():
    engine, calls = _make_engine(compute_signals=_always_none)
    candle = Candle(open_time_ms=0, open=100, high=100, low=100, close=100)

    engine._on_candle_closed(candle)

    assert calls["signal"] == []
    assert calls["order_placed"] == []
    assert engine._open_trade is None


def test_auto_mode_places_orders_immediately():
    engine, calls = _make_engine(mode="auto")
    candle = Candle(open_time_ms=0, open=100, high=100, low=100, close=100)

    with (
        patch("app.live_trading.engine.place_futures_market_order", return_value={"orderId": 1}) as mock_entry,
        patch("app.live_trading.engine.place_futures_stop_loss_order", return_value={"algoId": 2}) as mock_sl,
        patch("app.live_trading.engine.place_futures_take_profit_order", return_value={"algoId": 3}) as mock_tp,
    ):
        engine._on_candle_closed(candle)

    mock_entry.assert_called_once_with("key", "secret", "BTCUSDT", "BUY", pytest.approx(0.1))
    mock_sl.assert_called_once()
    mock_tp.assert_called_once()
    assert calls["signal"] == [("LONG", 100.0)]
    assert len(calls["order_placed"]) == 1
    assert engine._open_trade is not None
    assert engine._open_trade["side"] == "LONG"
    assert engine._open_trade["entry_order_id"] == 1
    assert engine._open_trade["sl_order_id"] == 2
    assert engine._open_trade["tp_order_id"] == 3


def test_confirm_mode_waits_for_confirmation_before_ordering():
    engine, calls = _make_engine(mode="confirm")
    candle = Candle(open_time_ms=0, open=100, high=100, low=100, close=100)

    with patch("app.live_trading.engine.place_futures_market_order") as mock_entry:
        engine._on_candle_closed(candle)
        mock_entry.assert_not_called()

    assert len(calls["confirmation"]) == 1
    assert engine._pending_signal == ("LONG", 100.0)
    assert engine._open_trade is None


def test_confirm_and_execute_places_orders_for_pending_signal():
    engine, calls = _make_engine(mode="confirm")
    candle = Candle(open_time_ms=0, open=100, high=100, low=100, close=100)
    engine._on_candle_closed(candle)

    with (
        patch("app.live_trading.engine.place_futures_market_order", return_value={"orderId": 1}),
        patch("app.live_trading.engine.place_futures_stop_loss_order", return_value={"algoId": 2}),
        patch("app.live_trading.engine.place_futures_take_profit_order", return_value={"algoId": 3}),
    ):
        engine.confirm_and_execute()

    assert engine._pending_signal is None
    assert len(calls["order_placed"]) == 1


def test_reject_pending_signal_never_places_order():
    engine, calls = _make_engine(mode="confirm")
    candle = Candle(open_time_ms=0, open=100, high=100, low=100, close=100)
    engine._on_candle_closed(candle)

    engine.reject_pending_signal()

    with patch("app.live_trading.engine.place_futures_market_order") as mock_entry:
        engine.confirm_and_execute()  # bekleyen sinyal temizlendiği için hiçbir şey yapmamalı
    mock_entry.assert_not_called()
    assert calls["order_placed"] == []


def test_position_open_blocks_new_signal():
    engine, calls = _make_engine(mode="auto")
    engine._open_trade = {"side": "LONG", "sl_order_id": 1, "tp_order_id": 2}
    candle = Candle(open_time_ms=0, open=100, high=100, low=100, close=100)

    with patch("app.live_trading.engine.place_futures_market_order") as mock_entry:
        engine._on_candle_closed(candle)

    mock_entry.assert_not_called()
    assert calls["signal"] == []


def test_execute_signal_error_reported_and_no_open_trade():
    engine, calls = _make_engine(mode="auto")
    candle = Candle(open_time_ms=0, open=100, high=100, low=100, close=100)

    with patch("app.live_trading.engine.place_futures_market_order", side_effect=RuntimeError("network down")):
        engine._on_candle_closed(candle)

    assert engine._open_trade is None
    assert len(calls["error"]) == 1
    assert "network down" in calls["error"][0]


def test_execute_signal_sl_tp_failure_still_tracks_open_position():
    # Giriş (MARKET) emri borsada GERÇEKLEŞTİ ama SL/TP yerleştirilemedi (ör.
    # ağ hatası/borsa reddi) -- pozisyon sessizce kaybolmamalı: _open_trade
    # yine de set edilip _poll_position_loop tarafından izlenmeye devam
    # etmeli, ve kullanıcıya pozisyonun KORUMASIZ kaldığı açıkça bildirilmeli.
    engine, calls = _make_engine(mode="auto")
    candle = Candle(open_time_ms=0, open=100, high=100, low=100, close=100)

    with (
        patch("app.live_trading.engine.place_futures_market_order", return_value={"orderId": 1}),
        patch("app.live_trading.engine.place_futures_stop_loss_order", side_effect=RuntimeError("-4120")),
        patch("app.live_trading.engine.place_futures_take_profit_order") as mock_tp,
    ):
        engine._on_candle_closed(candle)

    mock_tp.assert_not_called()  # SL zaten patladı, TP hiç denenmemeli
    assert engine._open_trade is not None
    assert engine._open_trade["entry_order_id"] == 1
    assert engine._open_trade["sl_order_id"] is None
    assert engine._open_trade["tp_order_id"] is None
    assert len(calls["order_placed"]) == 1  # UI yine de açık pozisyondan haberdar edilmeli
    assert len(calls["error"]) == 1
    assert "KORUMASIZ" in calls["error"][0]
    assert "-4120" in calls["error"][0]


def test_check_position_closed_detects_stop_loss_hit_and_cancels_tp():
    engine, calls = _make_engine(mode="auto")
    engine._open_trade = {"side": "LONG", "sl_order_id": 11, "tp_order_id": 22}

    with (
        patch("app.live_trading.engine.get_futures_position_risk", return_value=[{"positionAmt": "0"}]),
        patch("app.live_trading.engine.get_futures_open_algo_orders", return_value=[{"algoId": 22}]),
        patch("app.live_trading.engine.cancel_futures_algo_order") as mock_cancel,
    ):
        engine._check_position_closed()

    assert calls["position_closed"] == ["SL"]
    mock_cancel.assert_called_once_with("key", "secret", "BTCUSDT", 22)
    assert engine._open_trade is None


def test_check_position_closed_detects_take_profit_hit_and_cancels_sl():
    engine, calls = _make_engine(mode="auto")
    engine._open_trade = {"side": "LONG", "sl_order_id": 11, "tp_order_id": 22}

    with (
        patch("app.live_trading.engine.get_futures_position_risk", return_value=[{"positionAmt": "0"}]),
        patch("app.live_trading.engine.get_futures_open_algo_orders", return_value=[{"algoId": 11}]),
        patch("app.live_trading.engine.cancel_futures_algo_order") as mock_cancel,
    ):
        engine._check_position_closed()

    assert calls["position_closed"] == ["TP"]
    mock_cancel.assert_called_once_with("key", "secret", "BTCUSDT", 11)


def test_check_position_closed_does_nothing_while_position_still_open():
    engine, calls = _make_engine(mode="auto")
    engine._open_trade = {"side": "LONG", "sl_order_id": 11, "tp_order_id": 22}

    with patch("app.live_trading.engine.get_futures_position_risk", return_value=[{"positionAmt": "0.01"}]):
        engine._check_position_closed()

    assert calls["position_closed"] == []
    assert engine._open_trade is not None


def test_backfill_candles_drops_last_possibly_unclosed_kline():
    engine, _ = _make_engine(mode="auto")
    raw_klines = [
        [0, "100", "101", "99", "100", "1", 0, "0", 0, "0", "0", "0"],
        [300_000, "100", "101", "99", "100.5", "1", 0, "0", 0, "0", "0", "0"],
    ]

    with patch("app.live_trading.engine.get_futures_historical_klines", return_value=raw_klines):
        engine._backfill_candles()

    assert len(engine._candles) == 1
    assert engine._candles[0].open_time_ms == 0


def test_backfill_candles_parses_volume():
    engine, _ = _make_engine(mode="auto")
    raw_klines = [
        [0, "100", "101", "99", "100", "42.5", 0, "0", 0, "0", "0", "0"],
        [300_000, "100", "101", "99", "100.5", "1", 0, "0", 0, "0", "0", "0"],
    ]

    with patch("app.live_trading.engine.get_futures_historical_klines", return_value=raw_klines):
        engine._backfill_candles()

    assert engine._candles[0].volume == pytest.approx(42.5)


def test_max_holding_bars_force_closes_position_after_n_bars():
    engine, calls = _make_engine(mode="auto", compute_signals=_always_none, max_holding_bars=2)
    engine._open_trade = {"side": "LONG", "quantity": 0.1, "sl_order_id": 1, "tp_order_id": 2, "bars_since_entry": 0}

    with (
        patch("app.live_trading.engine.cancel_all_futures_open_orders") as mock_cancel_all,
        patch("app.live_trading.engine.cancel_futures_algo_order") as mock_cancel_algo,
        patch("app.live_trading.engine.place_futures_market_order") as mock_close_order,
    ):
        engine._on_candle_closed(Candle(open_time_ms=0, open=100, high=100, low=100, close=100))
        assert engine._open_trade is not None  # 1. mum: henüz zaman aşımına uğramadı
        mock_close_order.assert_not_called()

        engine._on_candle_closed(Candle(open_time_ms=60_000, open=100, high=100, low=100, close=100))

    mock_cancel_all.assert_called_once_with("key", "secret", "BTCUSDT")
    assert mock_cancel_algo.call_args_list == [
        (("key", "secret", "BTCUSDT", 1), {}),
        (("key", "secret", "BTCUSDT", 2), {}),
    ]
    mock_close_order.assert_called_once_with("key", "secret", "BTCUSDT", "SELL", 0.1, reduce_only=True)
    assert engine._open_trade is None
    assert calls["position_closed"] == ["TIME"]


def test_max_holding_bars_none_never_force_closes():
    engine, calls = _make_engine(mode="auto", compute_signals=_always_none, max_holding_bars=None)
    engine._open_trade = {"side": "LONG", "quantity": 0.1, "sl_order_id": 1, "tp_order_id": 2, "bars_since_entry": 0}

    with patch("app.live_trading.engine.place_futures_market_order") as mock_close_order:
        for _ in range(20):
            engine._on_candle_closed(Candle(open_time_ms=0, open=100, high=100, low=100, close=100))

    mock_close_order.assert_not_called()
    assert engine._open_trade is not None
    assert calls["position_closed"] == []
