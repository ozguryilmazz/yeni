import time
from collections import deque
from dataclasses import dataclass

from app.whale_tracker.models import ModuleSignal


@dataclass
class _Snapshot:
    timestamp: float
    open_interest: float


class OpenInterestDivergenceModule:
    """Modül A — Open Interest (OI) & Hacim Diverjans Modülü.

    Binance Futures'ın GET /fapi/v1/openInterest ile alınan anlık açık pozisyon
    verisini zaman içinde tutar. Fiyat yatay seyrederken OI'nin belirgin şekilde
    artması, piyasa yapıcıların/whale'lerin bir sıkışma (squeeze) öncesi sessizce
    pozisyon biriktirdiğine işaret edebilir — bu, tek başına yön belirtmeyen bir
    "birikim" sinyalidir (direction=None); yönü diğer modüller (funding rate,
    likidasyon) belirler.
    """

    def __init__(
        self,
        price_change_threshold_pct: float = 0.5,
        oi_change_threshold_pct: float = 5.0,
        window_seconds: float = 3600,
    ) -> None:
        self.price_change_threshold_pct = price_change_threshold_pct
        self.oi_change_threshold_pct = oi_change_threshold_pct
        self.window_seconds = window_seconds
        self._history: deque[_Snapshot] = deque()

    def update(self, open_interest: float, timestamp: float | None = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        self._history.append(_Snapshot(ts, open_interest))
        cutoff = ts - self.window_seconds
        while self._history and self._history[0].timestamp < cutoff:
            self._history.popleft()

    def evaluate(self, price_change_percent_1h: float) -> ModuleSignal:
        if len(self._history) < 2:
            return ModuleSignal(False, 0, "Yetersiz OI geçmişi (en az 2 örnek gerekli)")

        oldest = self._history[0].open_interest
        newest = self._history[-1].open_interest
        if oldest <= 0:
            return ModuleSignal(False, 0, "OI verisi geçersiz")

        oi_change_pct = (newest - oldest) / oldest * 100
        price_flat = abs(price_change_percent_1h) < self.price_change_threshold_pct
        oi_rising = oi_change_pct > self.oi_change_threshold_pct

        if price_flat and oi_rising:
            return ModuleSignal(
                True,
                100,
                f"Sıkışma/Squeeze birikimi: fiyat %{price_change_percent_1h:+.2f} sabit, "
                f"OI %{oi_change_pct:+.2f} arttı",
                direction=None,
            )
        return ModuleSignal(False, 0, f"OI değişimi %{oi_change_pct:+.2f}, fiyat %{price_change_percent_1h:+.2f}")
