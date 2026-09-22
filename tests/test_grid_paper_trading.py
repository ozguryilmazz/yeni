import asyncio
from unittest.mock import patch

import pytest

from app.backtest.engine import Candle
from app.grid_trading.grid import start_grid_engine
from app.grid_trading.paper_trading import MAX_CHART_CANDLES, GridPaperTradingEngine


def _candle(open_time_ms: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(open_time_ms=open_time_ms, open=open_, high=high, low=low, close=close)


def _make_engine(**overrides):
    calls = {"status": [], "snapshot": [], "liquidated": [], "error": []}
    defaults = dict(
        symbol="btcusdt",
        interval="5m",
        lower_price=90.0,
        upper_price=110.0,
        grid_count=2,
        capital_usd=100.0,
        leverage=1.0,
        fee_rate=0.0005,
        maintenance_margin_rate=0.005,
        on_status=lambda m: calls["status"].append(m),
        on_snapshot=lambda r, c: calls["snapshot"].append((r, c)),
        on_liquidated=lambda r: calls["liquidated"].append(r),
        on_error=lambda m: calls["error"].append(m),
    )
    defaults.update(overrides)
    return GridPaperTradingEngine(**defaults), calls


def test_symbol_is_uppercased():
    engine, _ = _make_engine(symbol="btcusdt")
    assert engine.symbol == "BTCUSDT"


def test_run_reports_error_and_never_starts_stream_when_price_fetch_fails():
    engine, calls = _make_engine()

    async def scenario():
        stop_event = asyncio.Event()
        with (
            patch(
                "app.grid_trading.paper_trading.get_futures_kline_stats",
                side_effect=RuntimeError("network down"),
            ),
            patch("app.grid_trading.paper_trading.KlineStreamListener") as mock_listener_cls,
        ):
            await engine.run(stop_event)
        mock_listener_cls.assert_not_called()

    asyncio.run(scenario())

    assert engine._state is None
    assert len(calls["error"]) == 1
    assert "network down" in calls["error"][0]
    assert calls["status"] == []
    assert calls["snapshot"] == []


def test_run_reports_error_when_reference_price_is_zero():
    engine, calls = _make_engine()

    async def scenario():
        stop_event = asyncio.Event()
        with (
            patch(
                "app.grid_trading.paper_trading.get_futures_kline_stats",
                return_value={"last_price": 0.0},
            ),
            patch("app.grid_trading.paper_trading.KlineStreamListener") as mock_listener_cls,
        ):
            await engine.run(stop_event)
        mock_listener_cls.assert_not_called()

    asyncio.run(scenario())
    assert len(calls["error"]) == 1
    assert engine._state is None


def test_run_reports_error_on_invalid_grid_params_without_starting_stream():
    # lower_price >= upper_price -> start_grid_engine (build_grid_levels) ValueError fırlatır;
    # bu, akış hiç başlamadan yakalanıp kullanıcıya iletilmeli.
    engine, calls = _make_engine(lower_price=110.0, upper_price=90.0)

    async def scenario():
        stop_event = asyncio.Event()
        with (
            patch(
                "app.grid_trading.paper_trading.get_futures_kline_stats",
                return_value={"last_price": 100.0},
            ),
            patch("app.grid_trading.paper_trading.KlineStreamListener") as mock_listener_cls,
        ):
            await engine.run(stop_event)
        mock_listener_cls.assert_not_called()

    asyncio.run(scenario())
    assert len(calls["error"]) == 1
    assert engine._state is None


def test_run_sets_up_grid_at_reference_price_and_emits_initial_snapshot():
    engine, calls = _make_engine(lower_price=90.0, upper_price=110.0, grid_count=4, capital_usd=400.0)

    async def fake_listener_run(stop_event, on_candle_closed):
        return  # akış hemen 'biter' -- gerçek WebSocket bağlantısı hiç denenmez

    async def scenario():
        stop_event = asyncio.Event()
        with (
            patch(
                "app.grid_trading.paper_trading.get_futures_kline_stats",
                return_value={"last_price": 100.0},
            ),
            patch("app.grid_trading.paper_trading.KlineStreamListener") as mock_listener_cls,
        ):
            mock_listener_cls.return_value.run = fake_listener_run
            await engine.run(stop_event)
        mock_listener_cls.assert_called_once_with("BTCUSDT", "5m", on_error=engine.on_status)

    asyncio.run(scenario())

    assert engine._state is not None
    assert engine._state.start_price == pytest.approx(100.0)
    assert len(calls["status"]) == 1
    assert "100" in calls["status"][0]
    assert len(calls["snapshot"]) == 1
    result, candles = calls["snapshot"][0]
    assert candles == []
    assert result.grid_levels[0] == pytest.approx(90.0)
    assert result.grid_levels[-1] == pytest.approx(110.0)


def test_on_candle_closed_advances_state_and_emits_snapshot_with_accumulated_candles():
    engine, calls = _make_engine(lower_price=90.0, upper_price=110.0, grid_count=2, capital_usd=200.0)
    engine._state = start_grid_engine(
        100.0, 0, 90.0, 110.0, 2, 200.0, leverage=1.0, fee_rate=0.0005, maintenance_margin_rate=0.005
    )

    candle = _candle(1, 100.0, 105.0, 95.0, 100.0)
    engine._on_candle_closed(candle)

    assert len(calls["snapshot"]) == 1
    result, candles = calls["snapshot"][0]
    assert candles == [candle]
    assert calls["liquidated"] == []

    second = _candle(2, 100.0, 106.0, 96.0, 101.0)
    engine._on_candle_closed(second)
    assert len(calls["snapshot"]) == 2
    _, candles2 = calls["snapshot"][1]
    assert candles2 == [candle, second]


def test_on_candle_closed_caps_accumulated_candles_at_max():
    engine, calls = _make_engine(lower_price=90.0, upper_price=110.0, grid_count=2, capital_usd=200.0)
    engine._state = start_grid_engine(
        100.0, 0, 90.0, 110.0, 2, 200.0, leverage=1.0, fee_rate=0.0005, maintenance_margin_rate=0.005
    )

    for i in range(MAX_CHART_CANDLES + 10):
        engine._on_candle_closed(_candle(i, 100.0, 100.5, 99.5, 100.0))

    _, candles = calls["snapshot"][-1]
    assert len(candles) == MAX_CHART_CANDLES


def test_on_candle_closed_liquidation_stops_engine_and_reports():
    engine, calls = _make_engine(
        lower_price=90.0, upper_price=110.0, grid_count=2, capital_usd=100.0, leverage=20.0
    )
    engine._state = start_grid_engine(
        100.0, 0, 90.0, 110.0, 2, 100.0, leverage=20.0, fee_rate=0.0005, maintenance_margin_rate=0.005
    )
    engine._stop_event = asyncio.Event()

    crash_candle = _candle(1, 100.0, 100.0, 50.0, 60.0)  # sert düşüş -> likidasyon
    engine._on_candle_closed(crash_candle)

    assert len(calls["liquidated"]) == 1
    assert calls["liquidated"][0].liquidated is True
    assert engine._stop_event.is_set()
    assert any("LİKİDE" in message for message in calls["status"])

    # Motor durduktan sonra gelen bir sonraki mum artık işlenmemeli (state donmuş kalmalı).
    calls["snapshot"].clear()
    engine._on_candle_closed(_candle(2, 60.0, 65.0, 55.0, 62.0))
    assert len(calls["snapshot"]) == 1
    assert calls["snapshot"][0][0].liquidated is True
