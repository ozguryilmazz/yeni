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
    entry_timing: str = "same_close"
    """'same_close': sinyal mumunun kendi kapanışında girilir (varsayılan).
    'next_open': sinyalden SONRAKİ mumun açılışında girilir — canlıda bu,
    sinyal algılanır algılanmaz anında emir gönderilmesiyle otomatik
    sağlanır (bkz. app.live_trading.engine); backtest'te ise engine.py
    bir sonraki mumu bekler (bkz. app.backtest.engine.run_backtest)."""
    max_holding_bars: int | None = None
    """Verilirse, pozisyon SL/TP'ye değmeden bu kadar mum açık kalırsa
    zorla kapatılır (bkz. app.backtest.engine.run_backtest ve
    app.live_trading.engine)."""
