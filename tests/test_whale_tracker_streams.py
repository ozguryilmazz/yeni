"""WebSocket mesaj ayrıştırma (gerçek bağlantı olmadan) ve engine orkestrasyon testleri."""

import asyncio
import json

import httpx

from app.whale_tracker.engine import WhaleTrapEngine
from app.whale_tracker.funding_rate import FundingRateAnomalyModule, MarkPriceStreamListener
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
    assert any(e["module"] == "liquidation" for e in events)


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


def test_liquidation_listener_surfaces_missing_websockets_dependency(monkeypatch):
    """`websockets` paketi kurulu değilse (veya import başka bir nedenle patlarsa) görev
    artık sessizce ölmüyor; hata Olay Günlüğü'ne düşüyor ve döngü yeniden deniyor —
    kullanıcının 'Emir Defteri: Henüz veri yok' gibi kalıcı, açıklanamayan bir durumla
    baş başa kalmasını önlüyor."""
    import sys

    monkeypatch.setitem(sys.modules, "websockets", None)

    tracker = LiquidationTracker()
    events: list[dict] = []
    listener = LiquidationStreamListener("BTCUSDT", tracker, on_event=events.append)

    async def scenario() -> None:
        stop_event = asyncio.Event()

        async def stop_soon() -> None:
            await asyncio.sleep(0.05)
            stop_event.set()

        await asyncio.gather(listener.run(stop_event), stop_soon())

    asyncio.run(scenario())

    assert events, "websockets eksikken hiçbir hata loglanmadı — görev sessizce ölmüş olabilir"
    assert all(e["module"] == "liquidation" for e in events)
    assert any("bağlantı hatası" in e["message"] for e in events)


# ---- OrderbookStreamListener.handle_message -------------------------------


def test_orderbook_listener_computes_bid_ask_sums():
    module = OrderbookImbalanceModule(up_pressure_ratio=2.5, down_pressure_ratio=0.4, confirmation_updates=3)
    listener = OrderbookStreamListener("BTCUSDT", module)
    received: list[ModuleSignal] = []

    message = json.dumps({"b": [["100", "3"], ["99", "3"]], "a": [["101", "2"]]})  # bid=6, ask=2 -> oran 3.0
    # anti-spoof doğrulama penceresi (3 ardışık güncelleme) dolana kadar aynı mesaj gelir
    listener.handle_message(message, received.append)
    listener.handle_message(message, received.append)
    listener.handle_message(message, received.append)

    assert len(received) == 3
    assert received[-1].triggered is True
    assert received[-1].direction == "LONG"


def test_orderbook_listener_handles_malformed_message_gracefully():
    module = OrderbookImbalanceModule()
    events: list[dict] = []
    listener = OrderbookStreamListener("BTCUSDT", module, on_event=events.append)

    listener.handle_message("garbage", lambda signal: None)

    assert any("ayrıştırma hatası" in e["message"] for e in events)


def test_orderbook_listener_surfaces_missing_websockets_dependency(monkeypatch):
    """LiquidationStreamListener'daki aynı sessiz-ölüm hatası burada da vardı: `websockets`
    import'u try/except dışındaydı, bu yüzden paket eksikse görev hiç loglamadan ölüyor ve
    Emir Defteri sekmesi sonsuza kadar 'Henüz veri yok' gösteriyordu."""
    import sys

    monkeypatch.setitem(sys.modules, "websockets", None)

    module = OrderbookImbalanceModule()
    events: list[dict] = []
    listener = OrderbookStreamListener("BTCUSDT", module, on_event=events.append)

    async def scenario() -> None:
        stop_event = asyncio.Event()

        async def stop_soon() -> None:
            await asyncio.sleep(0.05)
            stop_event.set()

        await asyncio.gather(listener.run(stop_event, lambda signal: None), stop_soon())

    asyncio.run(scenario())

    assert events, "websockets eksikken hiçbir hata loglanmadı — görev sessizce ölmüş olabilir"
    assert all(e["module"] == "orderbook" for e in events)
    assert any("bağlantı hatası" in e["message"] for e in events)


# ---- MarkPriceStreamListener.handle_message --------------------------------


def test_mark_price_listener_parses_funding_and_price():
    module = FundingRateAnomalyModule()
    listener = MarkPriceStreamListener("BTCUSDT", module)
    funding_signals: list[ModuleSignal] = []
    mark_prices: list[tuple[float, float]] = []

    message = json.dumps({"e": "markPriceUpdate", "E": 1690000000000, "s": "BTCUSDT", "p": "30123.45", "r": "-0.001"})
    listener.handle_message(message, funding_signals.append, lambda price, ts: mark_prices.append((price, ts)))

    assert len(funding_signals) == 1
    assert funding_signals[0].triggered is True
    assert funding_signals[0].direction == "LONG"  # çok negatif funding -> LONG
    assert mark_prices == [(30123.45, 1690000000.0)]


def test_mark_price_listener_handles_malformed_message_gracefully():
    module = FundingRateAnomalyModule()
    events: list[dict] = []
    listener = MarkPriceStreamListener("BTCUSDT", module, on_event=events.append)

    listener.handle_message("garbage", lambda signal: None, lambda price, ts: None)

    assert any("ayrıştırma hatası" in e["message"] for e in events)


def test_mark_price_listener_surfaces_missing_websockets_dependency(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "websockets", None)

    module = FundingRateAnomalyModule()
    events: list[dict] = []
    listener = MarkPriceStreamListener("BTCUSDT", module, on_event=events.append)

    async def scenario() -> None:
        stop_event = asyncio.Event()

        async def stop_soon() -> None:
            await asyncio.sleep(0.05)
            stop_event.set()

        await asyncio.gather(listener.run(stop_event, lambda signal: None, lambda price, ts: None), stop_soon())

    asyncio.run(scenario())

    assert events, "websockets eksikken hiçbir hata loglanmadı — görev sessizce ölmüş olabilir"
    assert all(e["module"] == "funding_rate" for e in events)
    assert any("bağlantı hatası" in e["message"] for e in events)


# ---- WhaleTrapEngine.poll_once (REST orkestrasyonu) ------------------------


def _mock_transport(klines: list[list], quote_volume_24h: str = "1000000") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fapi/v1/klines":
            return httpx.Response(200, json=klines)
        if request.url.path == "/fapi/v1/ticker/24hr":
            return httpx.Response(200, json={"symbol": "BTCUSDT", "quoteVolume": quote_volume_24h})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_engine_poll_once_combines_all_modules_and_emits_score():
    """poll_once artık OI'yi ve funding'i REST'ten çekmiyor (OI ayrı bir hızlı REST
    döngüsünden, funding markPrice WS'ten beslenir) — bu yüzden test bunları engine'in
    kendi state'ine, gerçek akışta olduğu gibi elle 'seed' ediyor, sadece klines ve 24s
    hacim mock'lu HTTP'den geliyor."""
    # 24 geçmiş mum (ortalama hacim 100) + 1 güncel mum (hacim 500, fiyat %2 yukarı)
    history_klines = [[i, "100", "100", "100", "100", "1", i, "100", 1, "0", "0", "0"] for i in range(24)]
    current_kline = [24, "100", "104", "99", "102", "5", 24, "500", 1, "0", "0", "0"]
    klines = history_klines + [current_kline]

    transport = _mock_transport(klines=klines, quote_volume_24h="2000000")

    scores: list[TrapScoreResult] = []
    events: list[dict] = []

    engine = WhaleTrapEngine("BTCUSDT", on_score=scores.append, on_event=events.append)
    # WS'ten geldiğini simüle etmek için funding sinyalini elle seed ediyoruz (çok negatif -> LONG).
    engine._latest_funding_signal = engine.funding_module.evaluate(-0.001)
    # OI modülüne iki örnek (gerçek akışta ayrı OI poll döngüsünden gelir): %5.26 artış.
    engine.oi_module.update(950.0, timestamp=0)
    engine.oi_module.update(1000.0, timestamp=50)
    # Mark price WS'ten gelen iki tick: %0.2 değişim (yatay), OI diverjansını tetikler.
    engine._on_mark_price_tick(100.0, 0)
    engine._on_mark_price_tick(100.2, 50)

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
    assert any(e["module"] == "open_interest" for e in events)  # mark-price tabanlı OI diverjansı tetiklendi
    # 24s hacmin %0.5'i = 10,000 (min eşik 1,000,000'dan küçük) -> min eşik geçerli kalır.
    assert engine.liquidation_tracker.threshold_usdt == engine.min_liquidation_threshold_usdt


def test_engine_poll_once_scales_liquidation_threshold_with_24h_volume():
    klines = [[0, "100", "100", "100", "100", "1", 0, "100", 1, "0", "0", "0"]]
    transport = _mock_transport(klines=klines, quote_volume_24h="500000000")  # 500M USDT

    engine = WhaleTrapEngine("BTCUSDT", on_score=lambda r: None, on_event=lambda e: None)

    async def run_poll() -> None:
        async with httpx.AsyncClient(transport=transport, base_url="https://fapi.binance.com") as client:
            await engine.poll_once(client)

    asyncio.run(run_poll())

    # %0.5 * 500M = 2.5M, varsayılan 1M taban değerinden büyük -> dinamik eşik geçerli olmalı.
    assert engine.liquidation_tracker.threshold_usdt == 2_500_000
