import asyncio
import time
from unittest.mock import patch

import pytest

from app.backtest.engine import Candle
from app.grid_trading.grid import start_grid_engine
from app.grid_trading.paper_trading import MAX_CHART_CANDLES, GridPaperTradingEngine


def _candle(open_time_ms: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(open_time_ms=open_time_ms, open=open_, high=high, low=low, close=close)


def _kline(open_time_ms: int, o: float, h: float, l: float, c: float, close_time_ms: int, volume: float = 1.0) -> list:
    # [openTime, open, high, low, close, volume, closeTime, quoteVolume, trades, ...]
    return [open_time_ms, str(o), str(h), str(l), str(c), str(volume), close_time_ms, "0", 1, "0", "0", "0"]


def _make_engine(**overrides):
    calls = {"setup": [], "status": [], "snapshot": [], "liquidated": [], "error": []}
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
        on_setup=lambda m: calls["setup"].append(m),
        on_status=lambda m: calls["status"].append(m),
        on_snapshot=lambda r, c: calls["snapshot"].append((r, c)),
        on_liquidated=lambda r: calls["liquidated"].append(r),
        on_error=lambda m: calls["error"].append(m),
    )
    defaults.update(overrides)
    return GridPaperTradingEngine(**defaults), calls


def _started_engine(**overrides):
    engine, calls = _make_engine(**overrides)
    engine._state = start_grid_engine(
        100.0, 0, 90.0, 110.0, 2, 200.0, leverage=1.0, fee_rate=0.0005, maintenance_margin_rate=0.005
    )
    return engine, calls


def test_symbol_is_uppercased():
    engine, _ = _make_engine(symbol="btcusdt")
    assert engine.symbol == "BTCUSDT"


def test_run_reports_error_and_never_polls_when_price_fetch_fails():
    engine, calls = _make_engine()

    async def scenario():
        stop_event = asyncio.Event()
        with (
            patch(
                "app.grid_trading.paper_trading.get_futures_kline_stats",
                side_effect=RuntimeError("network down"),
            ),
            patch("app.grid_trading.paper_trading.get_futures_recent_klines") as mock_recent_klines,
        ):
            await engine.run(stop_event)
        mock_recent_klines.assert_not_called()

    asyncio.run(scenario())

    assert engine._state is None
    assert len(calls["error"]) == 1
    assert "network down" in calls["error"][0]
    assert calls["setup"] == []
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
            patch("app.grid_trading.paper_trading.get_futures_recent_klines") as mock_recent_klines,
        ):
            await engine.run(stop_event)
        mock_recent_klines.assert_not_called()

    asyncio.run(scenario())
    assert len(calls["error"]) == 1
    assert engine._state is None


def test_run_reports_error_on_invalid_grid_params_without_polling():
    # lower_price >= upper_price -> start_grid_engine (build_grid_levels) ValueError fırlatır;
    # bu, polling hiç başlamadan yakalanıp kullanıcıya iletilmeli.
    engine, calls = _make_engine(lower_price=110.0, upper_price=90.0)

    async def scenario():
        stop_event = asyncio.Event()
        with (
            patch(
                "app.grid_trading.paper_trading.get_futures_kline_stats",
                return_value={"last_price": 100.0},
            ),
            patch("app.grid_trading.paper_trading.get_futures_recent_klines") as mock_recent_klines,
        ):
            await engine.run(stop_event)
        mock_recent_klines.assert_not_called()

    asyncio.run(scenario())
    assert len(calls["error"]) == 1
    assert engine._state is None


def test_run_sets_up_grid_at_reference_price_and_emits_initial_snapshot():
    engine, calls = _make_engine(
        lower_price=90.0, upper_price=110.0, grid_count=4, capital_usd=400.0, leverage=3.0, fee_rate=0.0005
    )

    async def scenario():
        stop_event = asyncio.Event()
        stop_event.set()  # _poll_loop hemen dönsün -- gerçek REST isteği hiç yapılmaz
        with (
            patch(
                "app.grid_trading.paper_trading.get_futures_kline_stats",
                return_value={"last_price": 100.0},
            ),
            patch("app.grid_trading.paper_trading.get_futures_recent_klines") as mock_recent_klines,
        ):
            await engine.run(stop_event)
        mock_recent_klines.assert_not_called()

    asyncio.run(scenario())

    assert engine._state is not None
    assert engine._state.start_price == pytest.approx(100.0)

    # Açılış koşulları (fiyat/sermaye/kaldıraç/komisyon/bakım marjini/aralık) BİR KEZ,
    # ayrı bir on_setup çağrısıyla raporlanmalı -- sonraki status mesajlarıyla ezilmemeli.
    assert len(calls["setup"]) == 1
    setup_message = calls["setup"][0]
    assert "100" in setup_message
    assert "400" in setup_message  # sermaye
    assert "3x" in setup_message  # kaldıraç
    assert "90" in setup_message and "110" in setup_message  # grid aralığı

    assert len(calls["status"]) == 1
    assert "izleniyor" in calls["status"][0]

    assert len(calls["snapshot"]) == 1
    result, candles = calls["snapshot"][0]
    # Gerçek mum henüz gelmedi ama grafik/grid çizgileri hemen görünsün diye
    # başlangıç fiyatında düz iki 'yer tutucu' mum verilmeli (bkz.
    # GridPaperTradingEngine.run) -- _render_price_chart en az bir mum
    # olmadan hiçbir şey çizmiyor (bkz. app.ui.grid_tab).
    assert len(candles) == 2
    assert candles[0].open == pytest.approx(100.0)
    assert candles[0].close == pytest.approx(100.0)
    assert candles[1].open_time_ms > candles[0].open_time_ms
    assert result.grid_levels[0] == pytest.approx(90.0)
    assert result.grid_levels[-1] == pytest.approx(110.0)


def test_poll_loop_processes_closed_candle_and_ignores_still_forming_one():
    engine, calls = _started_engine()
    now_ms = int(time.time() * 1000)
    closed = _kline(0, 100.0, 101.0, 99.0, 100.5, close_time_ms=now_ms - 1000)
    forming = _kline(300_000, 100.5, 102.0, 100.0, 101.0, close_time_ms=now_ms + 999_000)

    async def scenario():
        stop_event = asyncio.Event()

        def fake_recent_klines(symbol, interval, limit):
            stop_event.set()  # tek turdan sonra döngü dursun
            return [closed, forming]

        with patch("app.grid_trading.paper_trading.get_futures_recent_klines", side_effect=fake_recent_klines):
            await engine._poll_loop(stop_event)

    asyncio.run(scenario())

    assert len(calls["snapshot"]) == 1  # sadece kapanan mum işlendi, oluşmakta olan değil
    result, candles = calls["snapshot"][0]
    assert candles == [Candle(open_time_ms=0, open=100.0, high=101.0, low=99.0, close=100.5, volume=1.0)]
    assert engine._last_closed_open_time_ms == 0


def test_poll_loop_skips_already_processed_candle():
    engine, calls = _started_engine()
    engine._last_closed_open_time_ms = 300_000
    now_ms = int(time.time() * 1000)
    already_seen = _kline(0, 100.0, 101.0, 99.0, 100.5, close_time_ms=now_ms - 5000)
    same_as_last = _kline(300_000, 100.5, 102.0, 100.0, 101.0, close_time_ms=now_ms - 1000)

    async def scenario():
        stop_event = asyncio.Event()

        def fake_recent_klines(symbol, interval, limit):
            stop_event.set()
            return [already_seen, same_as_last]

        with patch("app.grid_trading.paper_trading.get_futures_recent_klines", side_effect=fake_recent_klines):
            await engine._poll_loop(stop_event)

    asyncio.run(scenario())

    assert calls["snapshot"] == []
    assert engine._last_closed_open_time_ms == 300_000  # değişmedi


def test_poll_loop_processes_multiple_missed_candles_in_order():
    # Bir önceki poll turunda ağ hatası gibi bir sebeple mum kaçırılmışsa,
    # bir sonraki turda hepsi (sadece en sonuncusu değil) sırayla işlenmeli.
    engine, calls = _started_engine()
    now_ms = int(time.time() * 1000)
    first = _kline(0, 100.0, 101.0, 99.0, 100.5, close_time_ms=now_ms - 10_000)
    second = _kline(300_000, 100.5, 102.0, 100.0, 101.0, close_time_ms=now_ms - 5_000)

    async def scenario():
        stop_event = asyncio.Event()

        def fake_recent_klines(symbol, interval, limit):
            stop_event.set()
            return [first, second]

        with patch("app.grid_trading.paper_trading.get_futures_recent_klines", side_effect=fake_recent_klines):
            await engine._poll_loop(stop_event)

    asyncio.run(scenario())

    assert len(calls["snapshot"]) == 2
    assert calls["snapshot"][0][1] == [Candle(open_time_ms=0, open=100.0, high=101.0, low=99.0, close=100.5, volume=1.0)]
    assert calls["snapshot"][1][1] == [
        Candle(open_time_ms=0, open=100.0, high=101.0, low=99.0, close=100.5, volume=1.0),
        Candle(open_time_ms=300_000, open=100.5, high=102.0, low=100.0, close=101.0, volume=1.0),
    ]
    assert engine._last_closed_open_time_ms == 300_000


def test_poll_loop_reports_status_on_fetch_error_and_does_not_crash():
    engine, calls = _started_engine()

    async def scenario():
        stop_event = asyncio.Event()

        def failing_fetch(symbol, interval, limit):
            stop_event.set()  # tek turdan sonra döngü dursun
            raise RuntimeError("network kaboom")

        with patch("app.grid_trading.paper_trading.get_futures_recent_klines", side_effect=failing_fetch):
            await engine._poll_loop(stop_event)

    asyncio.run(scenario())

    assert calls["snapshot"] == []
    assert len(calls["status"]) == 1
    assert "network kaboom" in calls["status"][0]


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
