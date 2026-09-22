import asyncio
import json
import time
from collections.abc import Callable

from app.backtest.engine import Candle

STALE_CONNECTION_SECONDS = 30
"""Binance, HENÜZ KAPANMAMIŞ mum güncellemelerini bile normalde saniyede
birkaç kez gönderir; bu kadar süre boyunca HİÇBİR mesaj gelmezse bağlantı
muhtemelen bir ağ cihazı (NAT/güvenlik duvarı) tarafından TCP seviyesinde
sessizce düşürülmüştür -- soket bunu fark etmeyebilir (temiz bir FIN/RST
olmadan). Kütüphanenin KENDİ ping/pong mekanizması (aşağıdaki
ping_interval/ping_timeout) bunu tespit etmek için çok yavaş kalabilir
(dakikalarca) -- bu yüzden mesaj akışı ayrıca izlenip gerekirse ERKEN
yeniden bağlanılır. Aksi halde kullanıcı hiçbir hata görmeden, uzun süre
donmuş/bayat veriyle baş başa kalabilir (bkz. app.grid_trading.paper_trading
gibi bu sınıfı canlı grafik/durum güncellemesi için kullanan akışlar)."""


class KlineStreamListener:
    """`<symbol>@kline_<interval>` WebSocket akışı — her mum KAPANDIĞINDA
    (payload'daki `k.x == true`) bir Candle üretip `on_candle_closed`
    callback'ine iletir. Mum henüz açıkken gelen ara güncellemeler yok
    sayılır — strateji sinyalleri sadece kapanmış mumlar üzerinden
    değerlendirilir (bkz. app.live_trading.engine). Bağlantı
    STALE_CONNECTION_SECONDS boyunca (kapanmamış mum güncellemeleri dahil)
    hiç mesaj almazsa canlı kabul edilmez, kendiliğinden yeniden bağlanılır."""

    def __init__(self, symbol: str, interval: str, on_error: Callable[[str], None] | None = None) -> None:
        self.symbol = symbol.lower()
        self.interval = interval
        self.on_error = on_error
        self.url = f"wss://fstream.binance.com/ws/{self.symbol}@kline_{interval}"

    async def run(self, stop_event: asyncio.Event, on_candle_closed: Callable[[Candle], None]) -> None:
        while not stop_event.is_set():
            try:
                import websockets  # noqa: PLC0415 - opsiyonel/ağır bağımlılık, sadece kullanıldığında import edilir

                async with websockets.connect(self.url, open_timeout=10, ping_interval=180, ping_timeout=600) as ws:
                    last_message_at = time.monotonic()
                    while not stop_event.is_set():
                        idle_seconds = time.monotonic() - last_message_at
                        if idle_seconds >= STALE_CONNECTION_SECONDS:
                            self._log_error(
                                f"{STALE_CONNECTION_SECONDS:.0f}sn'dir borsadan veri gelmedi, bağlantı "
                                f"muhtemelen sessizce koptu — yeniden bağlanılıyor."
                            )
                            break
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=min(5, STALE_CONNECTION_SECONDS - idle_seconds))
                        except asyncio.TimeoutError:
                            continue
                        last_message_at = time.monotonic()
                        self._handle_message(raw, on_candle_closed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - WS bağlantı hatası; yeniden denenecek
                self._log_error(f"WS bağlantı hatası, 5sn sonra yeniden denenecek: {exc}")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

    def _handle_message(self, raw: str, on_candle_closed: Callable[[Candle], None]) -> None:
        try:
            payload = json.loads(raw)
            k = payload["k"]
            if not k.get("x"):
                return  # mum henüz kapanmadı, ara tick
            candle = Candle(
                open_time_ms=int(k["t"]),
                open=float(k["o"]),
                high=float(k["h"]),
                low=float(k["l"]),
                close=float(k["c"]),
                volume=float(k["v"]),
            )
        except Exception as exc:  # noqa: BLE001 - bozuk/beklenmeyen mesaj formatı
            self._log_error(f"Mesaj ayrıştırma hatası: {exc}")
            return
        on_candle_closed(candle)

    def _log_error(self, message: str) -> None:
        if self.on_error is not None:
            self.on_error(message)
