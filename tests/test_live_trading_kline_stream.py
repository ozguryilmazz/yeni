import asyncio
import json
import sys
import types

from app.live_trading import kline_stream as kline_stream_module
from app.live_trading.kline_stream import KlineStreamListener


def _kline_message(open_time_ms: int, closed: bool) -> str:
    return json.dumps(
        {
            "e": "kline",
            "k": {"t": open_time_ms, "o": "100", "h": "101", "l": "99", "c": "100.5", "v": "10", "x": closed},
        }
    )


class _FakeWSConnection:
    """websockets.connect(...)'in async context manager + .recv() arayüzünü
    taklit eder -- gerçek ağ bağlantısı hiç kurmadan mesaj sırasını/gecikmesini
    kontrol edip KlineStreamListener'ı test eder."""

    def __init__(self, messages: list[tuple[float, str]]):
        self._messages = list(messages)  # (mesajdan önceki gecikme_saniye, ham_mesaj)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def recv(self):
        if not self._messages:
            await asyncio.sleep(3600)  # sonsuza kadar sessiz kal -- 'bayat bağlantı' senaryosu
        delay, message = self._messages.pop(0)
        if delay:
            await asyncio.sleep(delay)
        return message


def _install_fake_websockets(monkeypatch, connections: list[_FakeWSConnection]) -> None:
    def fake_connect(*args, **kwargs):
        # Bağlantılar tükenirse (testin durma süresi, art arda yeniden bağlanma
        # sayısından uzun sürerse) sonuncusunu tekrar tekrar döndür -- IndexError
        # yerine zararsız bir şekilde aynı (muhtemelen yine bayat) bağlantıya döner.
        if len(connections) > 1:
            return connections.pop(0)
        return connections[0]

    monkeypatch.setitem(sys.modules, "websockets", types.SimpleNamespace(connect=fake_connect))


def _run_with_timeout(listener: KlineStreamListener, on_candle_closed, duration: float) -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()

        async def stop_soon() -> None:
            await asyncio.sleep(duration)
            stop_event.set()

        await asyncio.gather(listener.run(stop_event, on_candle_closed), stop_soon())

    asyncio.run(scenario())


# ---- _handle_message ---------------------------------------------------


def test_handle_message_ignores_unclosed_candle():
    listener = KlineStreamListener("BTCUSDT", "5m")
    closed = []

    listener._handle_message(_kline_message(0, closed=False), closed.append)

    assert closed == []


def test_handle_message_parses_closed_candle():
    listener = KlineStreamListener("BTCUSDT", "5m")
    closed = []

    listener._handle_message(_kline_message(1000, closed=True), closed.append)

    assert len(closed) == 1
    assert closed[0].open_time_ms == 1000
    assert closed[0].close == 100.5


def test_handle_message_reports_malformed_message():
    errors = []
    listener = KlineStreamListener("BTCUSDT", "5m", on_error=errors.append)

    listener._handle_message("not-json-at-all", lambda c: None)

    assert any("ayrıştırma hatası" in e for e in errors)


# ---- stale connection watchdog -----------------------------------------


def test_stale_connection_triggers_reconnect_when_no_messages_arrive(monkeypatch):
    monkeypatch.setattr(kline_stream_module, "STALE_CONNECTION_SECONDS", 0.05)

    silent_conn = _FakeWSConnection([])  # hiç mesaj yok -- bayat kalacak
    recovering_conn = _FakeWSConnection([(0, _kline_message(0, closed=True))])
    _install_fake_websockets(monkeypatch, [silent_conn, recovering_conn])

    listener = KlineStreamListener("BTCUSDT", "5m")
    errors = []
    listener.on_error = errors.append
    closed_candles = []

    _run_with_timeout(listener, closed_candles.append, duration=0.3)

    assert any("sessizce koptu" in e for e in errors)
    assert len(closed_candles) == 1


def test_frequent_messages_prevent_spurious_stale_reconnect(monkeypatch):
    # Aralarında sık (staleness eşiğinin çok altında) mesaj gelen bir bağlantı --
    # bazıları henüz kapanmamış mum güncellemesi, sonuncusu kapanış -- yanlışlıkla
    # 'bayat' sayılıp koparılmamalı.
    monkeypatch.setattr(kline_stream_module, "STALE_CONNECTION_SECONDS", 0.2)

    messages = [
        (0.02, _kline_message(0, closed=False)),
        (0.02, _kline_message(0, closed=False)),
        (0.02, _kline_message(0, closed=True)),
    ]
    conn = _FakeWSConnection(messages)
    _install_fake_websockets(monkeypatch, [conn])

    listener = KlineStreamListener("BTCUSDT", "5m")
    errors = []
    listener.on_error = errors.append
    closed_candles = []

    _run_with_timeout(listener, closed_candles.append, duration=0.15)

    assert not any("sessizce koptu" in e for e in errors)
    assert len(closed_candles) == 1


def test_run_reconnects_when_websockets_import_fails(monkeypatch):
    """`websockets` paketi kurulu değilse (veya import başka bir nedenle patlarsa)
    görev sessizce ölmemeli -- hata bildirilir ve döngü yeniden dener (bkz.
    tests/test_whale_tracker_streams.py'deki eşdeğer test)."""
    monkeypatch.setitem(sys.modules, "websockets", None)

    listener = KlineStreamListener("BTCUSDT", "5m")
    errors = []
    listener.on_error = errors.append

    _run_with_timeout(listener, lambda c: None, duration=0.05)

    assert any("bağlantı hatası" in e for e in errors)
