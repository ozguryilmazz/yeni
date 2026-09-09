from dataclasses import dataclass
from datetime import datetime

from app.backtest.engine import EMA_TREND_PERIOD, NEUTRAL_FEE_MULT, BacktestResult, Candle, run_backtest
from app.binance_client import get_futures_historical_klines

INTERVAL = "5m"
INTERVAL_MS = 5 * 60_000
# EMA100'ün ilk mumlardaki seed sapmasını azaltmak için seçilen aralıktan önce
# ekstra ısınma mumu çekilir; bu mumlarda pozisyon açılmaz, yalnızca indikatörleri beslerler.
WARMUP_CANDLES = EMA_TREND_PERIOD * 3


@dataclass
class BacktestComparison:
    normal: BacktestResult
    reversed: BacktestResult
    neutral: BacktestResult


def _fetch_candles(symbol: str, start: datetime, end: datetime) -> tuple[list[Candle], int]:
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    if start_ms >= end_ms:
        raise ValueError("Başlangıç tarihi bitiş tarihinden önce olmalı")

    fetch_start_ms = start_ms - WARMUP_CANDLES * INTERVAL_MS
    raw_klines = get_futures_historical_klines(symbol.upper(), INTERVAL, fetch_start_ms, end_ms)
    if not raw_klines:
        raise ValueError("Seçilen aralık için mum verisi bulunamadı")

    candles = [
        Candle(
            open_time_ms=int(k[0]),
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
        )
        for k in raw_klines
    ]
    return candles, start_ms


def run_backtest_for_symbol(symbol: str, start: datetime, end: datetime, reverse: bool = False) -> BacktestResult:
    candles, start_ms = _fetch_candles(symbol, start, end)
    return run_backtest(candles, start_time_ms=start_ms, reverse=reverse)


def run_backtest_comparison(symbol: str, start: datetime, end: datetime) -> BacktestComparison:
    """Aynı mum verisi üzerinde üç varyantı tek seferde çalıştırır:

    - `normal`: stratejinin kendi sinyali (mevcut SL/TP komisyon çarpanlarıyla)
    - `reversed`: sinyalin tersi (LONG<->SHORT), yine kendi SL/TP çarpanlarıyla
    - `neutral`: normal yönde ama SL=TP (NEUTRAL_FEE_MULT) simetrik mesafeyle —
      hangi tarafın (SL/TP) entry'ye daha yakın olduğu kazanma oranını
      çarpıttığından, entry sinyalinin ham yön başarısını bu çarpıklıktan
      arındırılmış şekilde görmek için kullanılır.

    Veri tek seferde çekilip üçünde de tekrar kullanılır.
    """
    candles, start_ms = _fetch_candles(symbol, start, end)
    normal = run_backtest(candles, start_time_ms=start_ms, reverse=False)
    reversed_result = run_backtest(candles, start_time_ms=start_ms, reverse=True)
    neutral = run_backtest(
        candles, start_time_ms=start_ms, reverse=False, sl_fee_mult=NEUTRAL_FEE_MULT, tp_fee_mult=NEUTRAL_FEE_MULT
    )
    return BacktestComparison(normal=normal, reversed=reversed_result, neutral=neutral)
