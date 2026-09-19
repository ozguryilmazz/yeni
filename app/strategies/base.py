from collections.abc import Callable
from dataclasses import dataclass

from app.backtest.engine import Candle


@dataclass
class Strategy:
    """Takılabilir bir sinyal yöntemi: verilen mum dizisi üzerinde her mum
    için 'LONG' / 'SHORT' / None döner. Pozisyon açma/kapama, SL/TP ve
    komisyon muhasebesi stratejiden bağımsızdır (bkz. app.backtest.engine);
    strateji sadece yön kararını verir.

    Hem Backtest hem Canlı İşlem sekmesi, kayıtlı stratejiler arasından
    (bkz. app.strategies.registry) isimle seçim yapar."""

    name: str
    compute_signals: Callable[[list[Candle]], list[str | None]]
    warmup_candles: int
    """Bu stratejinin indikatörlerinin (ör. EMA100) ısınması için, işlem
    aralığından önce kaç ekstra mum çekilmesi gerektiği (bkz.
    app.backtest.service)."""
