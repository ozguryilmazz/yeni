import asyncio
from collections import deque
from collections.abc import Callable

import httpx

from app.whale_tracker.funding_rate import FundingRateAnomalyModule, MarkPriceStreamListener
from app.whale_tracker.liquidation import LiquidationStreamListener, LiquidationTracker
from app.whale_tracker.models import ModuleSignal, TrapScoreResult
from app.whale_tracker.open_interest import OpenInterestDivergenceModule
from app.whale_tracker.orderbook import OrderbookImbalanceModule, OrderbookStreamListener
from app.whale_tracker.rest_client import (
    FUTURES_BASE_URL,
    fetch_24h_quote_volume,
    fetch_funding_rate,
    fetch_open_interest,
    fetch_recent_klines,
)
from app.whale_tracker.scorer import TrapScorer
from app.whale_tracker.volume_surge import VolumeSurgeModule


class WhaleTrapEngine:
    """Tüm modülleri (OI, funding rate, likidasyon, emir defteri, hacim) tek bir
    sembol için birlikte çalıştırıp periyodik olarak Tuzak Skoru üreten asyncio
    orkestratörü.

    Veri kaynağı hızına göre üç ayrı döngü/akış çalışır:
    - **Funding rate + mark price**: `<symbol>@markPrice@1s` WebSocket akışı — Binance'ın
      funding rate için resmi bir push akışı olduğundan bu artık 15sn'lik REST poll'u
      beklemez, ~1sn'de bir güncellenir (squeeze anındaki REST/WS gecikme farkını azaltır).
      Aynı akıştaki mark price, OI diverjans modülünün 'fiyat yatay mı' kontrolünü de canlı
      besler.
    - **Open Interest**: Binance Futures'ta OI için resmi bir WebSocket push akışı YOKTUR
      (sadece REST). Bu yüzden ayrı, daha sık (OI_POLL_INTERVAL_SECONDS) bir REST poll
      döngüsüyle güncellenir — 15sn'lik ana döngüden bağımsız, daha taze tutulur.
    - **Likidasyon ve emir defteri**: sürekli açık WebSocket bağlantılarıyla anlık izlenir.
    - **Hacim baseline'ı + final skorlama**: ana REST poll döngüsünde (POLL_INTERVAL_SECONDS)
      klines + 24s hacim çekilir, o anki tüm modül durumları TrapScorer'dan geçirilip
      `on_score` ile dışarı iletilir. Tetiklenen her modül `on_event` ile ayrıca loglanır.
    """

    POLL_INTERVAL_SECONDS = 15
    OI_POLL_INTERVAL_SECONDS = 5
    LIQUIDATION_THRESHOLD_PCT_OF_24H_VOLUME = 0.005  # %0.5 — dinamik likidasyon eşiği

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
        # `liquidation_threshold_usdt` sabit bir alt taban (MIN) olarak kullanılır; gerçek
        # eşik her ana poll döngüsünde sembolün 24s hacminin bir yüzdesine göre güncellenir.
        self.min_liquidation_threshold_usdt = liquidation_threshold_usdt
        self.liquidation_tracker = LiquidationTracker(threshold_usdt=liquidation_threshold_usdt)
        self.orderbook_module = OrderbookImbalanceModule()
        self.scorer = TrapScorer()

        self._latest_orderbook_signal = ModuleSignal(False, 0, "Henüz veri yok")
        self._latest_funding_signal = ModuleSignal(False, 0, "Henüz veri yok")
        self._mark_price_history: deque[tuple[float, float]] = deque()
        self._mark_price_window_seconds = self.oi_module.window_seconds

    async def run(self, stop_event: asyncio.Event) -> None:
        async with httpx.AsyncClient(base_url=FUTURES_BASE_URL, timeout=10) as client:
            try:
                initial_funding_rate = await fetch_funding_rate(client, self.symbol)
                self._latest_funding_signal = self.funding_module.evaluate(initial_funding_rate)
            except Exception as exc:  # noqa: BLE001 - başlangıç seed'i başarısızsa WS zaten devam eder
                self.on_event({"module": "REST", "message": f"Başlangıç funding rate alınamadı: {exc}"})

            liquidation_listener = LiquidationStreamListener(self.symbol, self.liquidation_tracker, self.on_event)
            orderbook_listener = OrderbookStreamListener(self.symbol, self.orderbook_module, self.on_event)
            mark_price_listener = MarkPriceStreamListener(self.symbol, self.funding_module, self.on_event)

            tasks = [
                asyncio.create_task(self._poll_oi_loop(client, stop_event)),
                asyncio.create_task(self._poll_rest_loop(client, stop_event)),
                asyncio.create_task(liquidation_listener.run(stop_event)),
                asyncio.create_task(orderbook_listener.run(stop_event, self._on_orderbook_signal)),
                asyncio.create_task(
                    mark_price_listener.run(stop_event, self._on_funding_signal, self._on_mark_price_tick)
                ),
            ]
            try:
                await stop_event.wait()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    def _on_orderbook_signal(self, signal: ModuleSignal) -> None:
        self._latest_orderbook_signal = signal

    def _on_funding_signal(self, signal: ModuleSignal) -> None:
        self._latest_funding_signal = signal

    def _on_mark_price_tick(self, price: float, timestamp: float) -> None:
        self._mark_price_history.append((timestamp, price))
        cutoff = timestamp - self._mark_price_window_seconds
        while self._mark_price_history and self._mark_price_history[0][0] < cutoff:
            self._mark_price_history.popleft()

    def _mark_price_change_percent(self) -> float | None:
        """Mark price WS tick'lerinden canlı bir '1 saatlik fiyat değişimi' hesaplar
        (OI diverjans modülü için). Yeterli geçmiş birikene kadar None döner — bu
        durumda fiyatı 'yatay' varsayıp yanlışlıkla erken tetiklemek yerine OI
        değerlendirmesi tamamen atlanır (bkz. poll_once)."""
        if len(self._mark_price_history) < 2:
            return None
        oldest_price = self._mark_price_history[0][1]
        newest_price = self._mark_price_history[-1][1]
        if not oldest_price:
            return None
        return (newest_price - oldest_price) / oldest_price * 100

    async def _poll_oi_loop(self, client: httpx.AsyncClient, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                open_interest = await fetch_open_interest(client, self.symbol)
                self.oi_module.update(open_interest)
            except Exception as exc:  # noqa: BLE001 - tek bir başarısız fetch döngüyü durdurmasın
                self.on_event({"module": "REST", "message": f"OI verisi çekilemedi: {exc}"})

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.OI_POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass

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
        """Tek bir REST poll döngüsü: klines + 24s hacim çeker, likidasyon eşiğini
        dinamik günceller, tüm modülleri (OI ve funding artık kendi canlı akışlarından
        beslenir) değerlendirir, skoru hesaplayıp callback'lerle iletir ve sonucu döner
        (dönüş değeri esas olarak testler için kullanışlıdır)."""
        klines = await fetch_recent_klines(client, self.symbol, "1h", 25)

        try:
            quote_volume_24h = await fetch_24h_quote_volume(client, self.symbol)
            dynamic_threshold = max(
                self.min_liquidation_threshold_usdt, quote_volume_24h * self.LIQUIDATION_THRESHOLD_PCT_OF_24H_VOLUME
            )
            self.liquidation_tracker.update_threshold(dynamic_threshold)
        except Exception as exc:  # noqa: BLE001 - eşik güncellenemezse mevcut eşikle devam et
            self.on_event({"module": "REST", "message": f"24s hacim çekilemedi, likidasyon eşiği güncellenmedi: {exc}"})

        kline_price_change_percent = 0.0
        current_volume = 0.0
        average_volume = 0.0
        if klines:
            last = klines[-1]
            open_price, close_price = float(last[1]), float(last[4])
            if open_price:
                kline_price_change_percent = (close_price - open_price) / open_price * 100
            current_volume = float(last[7])
            history = klines[:-1] or klines
            average_volume = sum(float(k[7]) for k in history) / len(history)

        mark_price_change_percent = self._mark_price_change_percent()
        if mark_price_change_percent is None:
            oi_signal = ModuleSignal(False, 0, "Yetersiz canlı fiyat geçmişi (mark price), OI diverjansı henüz değerlendirilemiyor")
        else:
            oi_signal = self.oi_module.evaluate(mark_price_change_percent)

        signals: dict[str, ModuleSignal] = {
            "open_interest": oi_signal,
            "funding_rate": self._latest_funding_signal,
            "volume": self.volume_module.evaluate(current_volume, average_volume, kline_price_change_percent),
            "liquidation": self.liquidation_tracker.evaluate(),
            "orderbook": self._latest_orderbook_signal,
        }

        result = self.scorer.score(signals)
        self.on_score(result)

        for name, signal in signals.items():
            if signal.triggered:
                self.on_event({"module": name, "message": signal.message})

        return result
