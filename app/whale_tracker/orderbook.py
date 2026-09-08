import asyncio
import json
from collections.abc import Callable

from app.whale_tracker.models import ModuleSignal


class OrderbookImbalanceModule:
    """Modül D (mantık kısmı) — Orderbook Imbalance & Spoofing Modülü.

    Toplam bid (alış) hacminin toplam ask (satış) hacmine oranını değerlendirir.
    Oran > up_pressure_ratio ise alış tarafı baskın (yukarı baskı); oran <
    down_pressure_ratio ise satış tarafı baskın (aşağı baskı).
    """

    def __init__(self, up_pressure_ratio: float = 2.5, down_pressure_ratio: float = 0.4) -> None:
        self.up_pressure_ratio = up_pressure_ratio
        self.down_pressure_ratio = down_pressure_ratio

    def evaluate(self, bid_volume: float, ask_volume: float) -> ModuleSignal:
        if ask_volume <= 0 or bid_volume <= 0:
            return ModuleSignal(False, 0, "Emir defteri verisi yetersiz")

        ratio = bid_volume / ask_volume
        if ratio > self.up_pressure_ratio:
            return ModuleSignal(True, 100, f"Bid/Ask oranı {ratio:.2f} — yukarı baskı", direction="LONG")
        if ratio < self.down_pressure_ratio:
            return ModuleSignal(True, 100, f"Bid/Ask oranı {ratio:.2f} — aşağı baskı", direction="SHORT")
        return ModuleSignal(False, 0, f"Bid/Ask oranı {ratio:.2f} nötr")


class OrderbookStreamListener:
    """`<symbol>@depth20@100ms` Partial Book Depth WebSocket akışı — ilk 20 seviye
    bid/ask, 100ms güncelleme. Spoofing/imbalance hesaplamak için tam L2 defterine
    gerek yoktur, bu yeterlidir. Her güncellemede `module.evaluate(...)` çağrılıp
    sonuç `on_signal` callback'ine iletilir."""

    def __init__(self, symbol: str, module: OrderbookImbalanceModule, on_event: Callable[[dict], None] | None = None) -> None:
        self.symbol = symbol.lower()
        self.module = module
        self.on_event = on_event
        self.url = f"wss://fstream.binance.com/ws/{self.symbol}@depth20@100ms"

    async def run(self, stop_event: asyncio.Event, on_signal: Callable[[ModuleSignal], None]) -> None:
        import websockets  # noqa: PLC0415 - opsiyonel/ağır bağımlılık, sadece kullanıldığında import edilir

        while not stop_event.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=180, ping_timeout=600) as ws:
                    while not stop_event.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        except asyncio.TimeoutError:
                            continue
                        self.handle_message(raw, on_signal)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - WS bağlantı hatası; yeniden denenecek
                self._log_event("Orderbook", f"WS bağlantı hatası, 5sn sonra yeniden denenecek: {exc}")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

    def handle_message(self, raw: str, on_signal: Callable[[ModuleSignal], None]) -> None:
        try:
            payload = json.loads(raw)
            bids = payload.get("b", [])
            asks = payload.get("a", [])
            bid_volume = sum(float(qty) for _price, qty in bids)
            ask_volume = sum(float(qty) for _price, qty in asks)
            signal = self.module.evaluate(bid_volume, ask_volume)
            on_signal(signal)
        except Exception as exc:  # noqa: BLE001 - bozuk/beklenmeyen mesaj formatı
            self._log_event("Orderbook", f"Mesaj ayrıştırma hatası: {exc}")

    def _log_event(self, module: str, message: str) -> None:
        if self.on_event is not None:
            self.on_event({"module": module, "message": message})
