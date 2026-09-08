import asyncio
from collections.abc import Callable

import httpx

from app.whale_tracker.funding_rate import FundingRateAnomalyModule
from app.whale_tracker.liquidation import LiquidationStreamListener, LiquidationTracker
from app.whale_tracker.models import ModuleSignal, TrapScoreResult
from app.whale_tracker.open_interest import OpenInterestDivergenceModule
from app.whale_tracker.orderbook import OrderbookImbalanceModule, OrderbookStreamListener
from app.whale_tracker.rest_client import FUTURES_BASE_URL, fetch_funding_rate, fetch_open_interest, fetch_recent_klines
from app.whale_tracker.scorer import TrapScorer
from app.whale_tracker.volume_surge import VolumeSurgeModule


class WhaleTrapEngine:
    """Tüm modülleri (OI, funding rate, likidasyon, emir defteri, hacim) tek bir
    sembol için birlikte çalıştırıp periyodik olarak Tuzak Skoru üreten asyncio
    orkestratörü.

    - OI, funding rate ve hacim baseline'ı REST üzerinden periyodik (POLL_INTERVAL_SECONDS)
      olarak çekilir.
    - Likidasyon ve emir defteri, sürekli açık WebSocket bağlantılarıyla anlık izlenir.
    - Her REST poll döngüsünde, o anki en güncel likidasyon/emir defteri sinyalleriyle
      birlikte tüm modüller değerlendirilip TrapScorer'dan geçirilir; sonuç `on_score`
      callback'i ile dışarı iletilir. Tetiklenen her modül `on_event` ile ayrıca loglanır.
    """

    POLL_INTERVAL_SECONDS = 15

    def __init__(
        self,
        symbol: str,
        on_score: Callable[[TrapScoreResult], None],
        on_event: Callable[[dict], None],
        liquidation_threshold_usdt: float = 1_000_000,
    ) -> None:
        self.symbol = symbol.upper()
        self.on_score = on_score
        self.on_event = on_event

        self.oi_module = OpenInterestDivergenceModule()
        self.funding_module = FundingRateAnomalyModule()
        self.volume_module = VolumeSurgeModule()
        self.liquidation_tracker = LiquidationTracker(threshold_usdt=liquidation_threshold_usdt)
        self.orderbook_module = OrderbookImbalanceModule()
        self.scorer = TrapScorer()

        self._latest_orderbook_signal = ModuleSignal(False, 0, "Henüz veri yok")

    async def run(self, stop_event: asyncio.Event) -> None:
        async with httpx.AsyncClient(base_url=FUTURES_BASE_URL, timeout=10) as client:
            liquidation_listener = LiquidationStreamListener(self.symbol, self.liquidation_tracker, self.on_event)
            orderbook_listener = OrderbookStreamListener(self.symbol, self.orderbook_module, self.on_event)

            tasks = [
                asyncio.create_task(self._poll_rest_loop(client, stop_event)),
                asyncio.create_task(liquidation_listener.run(stop_event)),
                asyncio.create_task(orderbook_listener.run(stop_event, self._on_orderbook_signal)),
            ]
            try:
                await stop_event.wait()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    def _on_orderbook_signal(self, signal: ModuleSignal) -> None:
        self._latest_orderbook_signal = signal

    async def _poll_rest_loop(self, client: httpx.AsyncClient, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.poll_once(client)
            except Exception as exc:  # noqa: BLE001 - tek bir başarısız poll döngüyü durdurmasın
                self.on_event({"module": "REST", "message": f"Veri çekilemedi: {exc}"})

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def poll_once(self, client: httpx.AsyncClient) -> TrapScoreResult:
        """Tek bir REST poll döngüsü: OI/funding/kline çeker, tüm modülleri
        değerlendirir, skoru hesaplayıp callback'lerle iletir ve sonucu döner
        (dönüş değeri esas olarak testler için kullanışlıdır)."""
        open_interest = await fetch_open_interest(client, self.symbol)
        funding_rate = await fetch_funding_rate(client, self.symbol)
        klines = await fetch_recent_klines(client, self.symbol, "1h", 25)

        self.oi_module.update(open_interest)

        price_change_percent = 0.0
        current_volume = 0.0
        average_volume = 0.0
        if klines:
            last = klines[-1]
            open_price, close_price = float(last[1]), float(last[4])
            if open_price:
                price_change_percent = (close_price - open_price) / open_price * 100
            current_volume = float(last[7])
            history = klines[:-1] or klines
            average_volume = sum(float(k[7]) for k in history) / len(history)

        signals: dict[str, ModuleSignal] = {
            "open_interest": self.oi_module.evaluate(price_change_percent),
            "funding_rate": self.funding_module.evaluate(funding_rate),
            "volume": self.volume_module.evaluate(current_volume, average_volume, price_change_percent),
            "liquidation": self.liquidation_tracker.evaluate(),
            "orderbook": self._latest_orderbook_signal,
        }

        result = self.scorer.score(signals)
        self.on_score(result)

        for name, signal in signals.items():
            if signal.triggered:
                self.on_event({"module": name, "message": signal.message})

        return result
