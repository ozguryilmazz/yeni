import asyncio
import json
import time
from collections.abc import Callable

from app.whale_tracker.models import ModuleSignal


class FundingRateAnomalyModule:
    """Modül B — Funding Rate (Fonlama Oranı) Anomali Modülü.

    Binance Futures'ın GET /fapi/v1/premiumIndex ile alınan `lastFundingRate` değerini
    değerlendirir. Bu değer ondalık bir orandır (0.0001 = %0.01), yüzde değil.

    - Funding Rate çok negatifse (< short_squeeze_threshold, ör. -%0.03): piyasa aşırı
      short ağırlıklı demektir — short'lar fonlama ödüyor, bu da bir Long Squeeze
      (short'ların zorla kapanıp fiyatı yukarı itmesi) ihtimalini artırır → LONG sinyali.
    - Funding Rate çok pozitifse (> long_squeeze_threshold, ör. +%0.05): piyasa aşırı
      long ağırlıklı demektir → Short Squeeze ihtimali → SHORT sinyali.
    """

    def __init__(
        self,
        short_squeeze_threshold: float = -0.0003,  # -%0.03
        long_squeeze_threshold: float = 0.0005,  # +%0.05
    ) -> None:
        self.short_squeeze_threshold = short_squeeze_threshold
        self.long_squeeze_threshold = long_squeeze_threshold

    def evaluate(self, funding_rate: float) -> ModuleSignal:
        if funding_rate <= self.short_squeeze_threshold:
            return ModuleSignal(
                True,
                100,
                f"Funding Rate %{funding_rate * 100:+.4f} — aşırı short ağırlıklı (Long Squeeze ihtimali)",
                direction="LONG",
            )
        if funding_rate >= self.long_squeeze_threshold:
            return ModuleSignal(
                True,
                100,
                f"Funding Rate %{funding_rate * 100:+.4f} — aşırı long ağırlıklı (Short Squeeze ihtimali)",
                direction="SHORT",
            )
        return ModuleSignal(False, 0, f"Funding Rate %{funding_rate * 100:+.4f} normal aralıkta")


class MarkPriceStreamListener:
    """`<symbol>@markPrice@1s` WebSocket akışı — Binance Futures'ta Open Interest'in
    aksine funding rate (`r` alanı) VE mark price (`p` alanı) için resmi bir push akışı
    vardır. Bunu kullanmak, funding rate'i 15 saniyelik REST poll döngüsünü beklemeden
    ~1 saniyede bir günceller; bu da squeeze mumu başladığı anda REST/WS arasındaki
    gecikme farkını (latency shift) büyük ölçüde azaltır.

    Ayrıca her tick'teki mark price, engine'in Open Interest diverjans modülü için canlı
    bir "1 saatlik fiyat değişimi" hesaplaması yapabilmesi amacıyla `on_mark_price`
    callback'i ile ayrıca iletilir (OI'nin kendisi hâlâ REST'ten gelir — Binance Futures'ta
    Open Interest için resmi bir WebSocket push akışı YOKTUR, sadece REST endpoint'i vardır)."""

    def __init__(
        self, symbol: str, funding_module: FundingRateAnomalyModule, on_event: Callable[[dict], None] | None = None
    ) -> None:
        self.symbol = symbol.lower()
        self.funding_module = funding_module
        self.on_event = on_event
        self.url = f"wss://fstream.binance.com/ws/{self.symbol}@markPrice@1s"

    async def run(
        self,
        stop_event: asyncio.Event,
        on_funding_signal: Callable[[ModuleSignal], None],
        on_mark_price: Callable[[float, float], None],
    ) -> None:
        while not stop_event.is_set():
            try:
                import websockets  # noqa: PLC0415 - opsiyonel/ağır bağımlılık, sadece kullanıldığında import edilir

                async with websockets.connect(self.url, ping_interval=180, ping_timeout=600) as ws:
                    while not stop_event.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        except asyncio.TimeoutError:
                            continue
                        self.handle_message(raw, on_funding_signal, on_mark_price)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - WS bağlantı hatası; yeniden denenecek
                self._log_event("funding_rate", f"WS bağlantı hatası, 5sn sonra yeniden denenecek: {exc}")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

    def handle_message(
        self,
        raw: str,
        on_funding_signal: Callable[[ModuleSignal], None],
        on_mark_price: Callable[[float, float], None],
    ) -> None:
        try:
            payload = json.loads(raw)
            funding_rate = float(payload["r"])
            mark_price = float(payload["p"])
            timestamp = float(payload["E"]) / 1000 if payload.get("E") else time.time()

            on_funding_signal(self.funding_module.evaluate(funding_rate))
            on_mark_price(mark_price, timestamp)
        except Exception as exc:  # noqa: BLE001 - bozuk/beklenmeyen mesaj formatı
            self._log_event("funding_rate", f"Mesaj ayrıştırma hatası: {exc}")

    def _log_event(self, module: str, message: str) -> None:
        if self.on_event is not None:
            self.on_event({"module": module, "message": message})
