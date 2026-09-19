from dataclasses import dataclass
from datetime import datetime

from app.backtest.engine import BacktestResult, Candle, run_backtest
from app.binance_client import INTERVAL_MS_MAP, get_futures_historical_klines
from app.position_sizing import NEUTRAL_FEE_MULT
from app.strategies.registry import DEFAULT_STRATEGY_NAME, get_strategy

DEFAULT_INTERVAL = "5m"
SUPPORTED_INTERVALS = ["5m", "15m", "1h"]


@dataclass
class BacktestComparison:
    normal: BacktestResult
    reversed: BacktestResult
    neutral: BacktestResult


def _fetch_candles(
    symbol: str, start: datetime, end: datetime, interval: str, warmup_candles: int
) -> tuple[list[Candle], int]:
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    if start_ms >= end_ms:
        raise ValueError("Başlangıç tarihi bitiş tarihinden önce olmalı")

    interval_ms = INTERVAL_MS_MAP[interval]
    fetch_start_ms = start_ms - warmup_candles * interval_ms
    raw_klines = get_futures_historical_klines(symbol.upper(), interval, fetch_start_ms, end_ms)
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


def run_backtest_for_symbol(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str = DEFAULT_INTERVAL,
    strategy_name: str = DEFAULT_STRATEGY_NAME,
    reverse: bool = False,
) -> BacktestResult:
    strategy = get_strategy(strategy_name)
    candles, start_ms = _fetch_candles(symbol, start, end, interval, strategy.warmup_candles)
    return run_backtest(candles, start_time_ms=start_ms, compute_signals=strategy.compute_signals, reverse=reverse)


def run_backtest_comparison(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str = DEFAULT_INTERVAL,
    strategy_name: str = DEFAULT_STRATEGY_NAME,
) -> BacktestComparison:
    """Aynı mum verisi üzerinde üç varyantı tek seferde çalıştırır:

    - `normal`: seçilen stratejinin kendi sinyali (mevcut SL/TP komisyon çarpanlarıyla)
    - `reversed`: sinyalin tersi (LONG<->SHORT), yine kendi SL/TP çarpanlarıyla
    - `neutral`: normal yönde ama SL=TP (NEUTRAL_FEE_MULT) simetrik mesafeyle —
      hangi tarafın (SL/TP) entry'ye daha yakın olduğu kazanma oranını
      çarpıttığından, entry sinyalinin ham yön başarısını bu çarpıklıktan
      arındırılmış şekilde görmek için kullanılır.

    Veri tek seferde çekilip üçünde de tekrar kullanılır.
    """
    strategy = get_strategy(strategy_name)
    candles, start_ms = _fetch_candles(symbol, start, end, interval, strategy.warmup_candles)
    normal = run_backtest(candles, start_time_ms=start_ms, compute_signals=strategy.compute_signals, reverse=False)
    reversed_result = run_backtest(
        candles, start_time_ms=start_ms, compute_signals=strategy.compute_signals, reverse=True
    )
    neutral = run_backtest(
        candles,
        start_time_ms=start_ms,
        compute_signals=strategy.compute_signals,
        reverse=False,
        sl_fee_mult=NEUTRAL_FEE_MULT,
        tp_fee_mult=NEUTRAL_FEE_MULT,
    )
    return BacktestComparison(normal=normal, reversed=reversed_result, neutral=neutral)
