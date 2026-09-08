"""WebSocket mesaj ayrıştırma (gerçek bağlantı olmadan) ve engine orkestrasyon testleri."""

import asyncio
import json

import httpx

from app.whale_tracker.engine import WhaleTrapEngine
from app.whale_tracker.liquidation import LiquidationStreamListener, LiquidationTracker
from app.whale_tracker.models import ModuleSignal, TrapScoreResult
from app.whale_tracker.orderbook import OrderbookImbalanceModule, OrderbookStreamListener


# ---- LiquidationStreamListener.handle_message -----------------------------


def test_liquidation_listener_parses_matching_symbol():
    tracker = LiquidationTracker(threshold_usdt=1)
    events: list[dict] = []
    listener = LiquidationStreamListener("BTCUSDT", tracker, on_event=events.append)

    message = json.dumps(
        {
            "e": "forceOrder",
            "E": 1690000000000,
            "o": {"s": "BTCUSDT", "S": "SELL", "q": "0.5", "p": "30000", "ap": "30000"},
        }
    )
    listener.handle_message(message)

    signal = tracker.evaluate()
    assert signal.triggered is True
    assert signal.direction == "SHORT"  # LONG likide oldu -> tersine SHORT
    assert any(e["module"] == "Liquidation" for e in events)


def test_liquidation_listener_ignores_other_symbols():
    tracker = LiquidationTracker(threshold_usdt=1)
    listener = LiquidationStreamListener("BTCUSDT", tracker)

    message = json.dumps({"e": "forceOrder", "o": {"s": "ETHUSDT", "S": "SELL", "q": "10", "p": "2000"}})
    listener.handle_message(message)

    assert tracker.evaluate().triggered is False


def test_liquidation_listener_handles_malformed_message_gracefully():
    tracker = LiquidationTracker()
    events: list[dict] = []
    listener = LiquidationStreamListener("BTCUSDT", tracker, on_event=events.append)

    listener.handle_message("not-json-at-all")

    assert any("ayrıştırma hatası" in e["message"] for e in events)


# ---- OrderbookStreamListener.handle_message -------------------------------


def test_orderbook_listener_computes_bid_ask_sums():
    module = OrderbookImbalanceModule(up_pressure_ratio=2.5, down_pressure_ratio=0.4)
    listener = OrderbookStreamListener("BTCUSDT", module)
    received: list[ModuleSignal] = []

    message = json.dumps({"b": [["100", "3"], ["99", "3"]], "a": [["101", "2"]]})  # bid=6, ask=2 -> oran 3.0
    listener.handle_message(message, received.append)

    assert len(received) == 1
    assert received[0].triggered is True
    assert received[0].direction == "LONG"


def test_orderbook_listener_handles_malformed_message_gracefully():
    module = OrderbookImbalanceModule()
    events: list[dict] = []
    listener = OrderbookStreamListener("BTCUSDT", module, on_event=events.append)

    listener.handle_message("garbage", lambda signal: None)

    assert any("ayrıştırma hatası" in e["message"] for e in events)


# ---- WhaleTrapEngine.poll_once (REST orkestrasyonu) ------------------------


def _mock_transport(open_interest: str, funding_rate: str, klines: list[list]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fapi/v1/openInterest":
            return httpx.Response(200, json={"openInterest": open_interest, "symbol": "BTCUSDT"})
        if request.url.path == "/fapi/v1/premiumIndex":
            return httpx.Response(200, json={"lastFundingRate": funding_rate, "symbol": "BTCUSDT"})
        if request.url.path == "/fapi/v1/klines":
            return httpx.Response(200, json=klines)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_engine_poll_once_combines_all_modules_and_emits_score():
    # 24 geçmiş mum (ortalama hacim 100) + 1 güncel mum (hacim 500, fiyat %2 yukarı)
    history_klines = [[i, "100", "100", "100", "100", "1", i, "100", 1, "0", "0", "0"] for i in range(24)]
    current_kline = [24, "100", "104", "99", "102", "5", 24, "500", 1, "0", "0", "0"]
    klines = history_klines + [current_kline]

    transport = _mock_transport(open_interest="1000", funding_rate="-0.001", klines=klines)

    scores: list[TrapScoreResult] = []
    events: list[dict] = []

    engine = WhaleTrapEngine("BTCUSDT", on_score=scores.append, on_event=events.append)
    # OI modülüne bir önceki örneği elle ekleyip (gerçek akışta iki poll sonrası oluşur)
    # ilk poll_once çağrısının tek başına diverjans tespit edebilmesini sağlıyoruz.
    engine.oi_module.update(950.0, timestamp=0)

    async def run_poll() -> None:
        async with httpx.AsyncClient(transport=transport, base_url="https://fapi.binance.com") as client:
            await engine.poll_once(client)

    asyncio.run(run_poll())

    assert len(scores) == 1
    result = scores[0]
    assert isinstance(result, TrapScoreResult)
    assert result.direction == "LONG"
    assert result.score > 0
    assert any(e["module"] == "funding_rate" for e in events)
