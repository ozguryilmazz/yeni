from dataclasses import dataclass
from datetime import datetime

from app.backtest.engine import EMA_TREND_PERIOD, BacktestResult, Candle, run_backtest
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
    """Aynı mum verisi üzerinde hem stratejinin normal yönünü hem de tam tersini
    (LONG<->SHORT) tek seferde çalıştırır — ters sinyalle işlem açmanın gerçekte
    ne verdiğini, veriyi iki kez çekmeden karşılaştırmak için kullanılır."""
    candles, start_ms = _fetch_candles(symbol, start, end)
    normal = run_backtest(candles, start_time_ms=start_ms, reverse=False)
    reversed_result = run_backtest(candles, start_time_ms=start_ms, reverse=True)
    return BacktestComparison(normal=normal, reversed=reversed_result)
