import time
from dataclasses import dataclass
from datetime import datetime

from app.backtest.engine import Candle
from app.binance_client import INTERVAL_MS_MAP, get_futures_historical_klines
from app.grid_trading.grid import DEFAULT_GRID_COUNT, GridBacktestResult, run_grid_backtest
from app.grid_trading.range_methods import DEFAULT_RANGE_METHOD, GridRange, compute_range

DEFAULT_RANGE_INTERVAL = "4h"
DEFAULT_RANGE_LOOKBACK_CANDLES = 120
"""ATR(14)/Bollinger(20)/destek-direnç kümelemesi için yeterden fazla ısınma
mumu; 4h'de ~20 gün, 1d'de ~4 ay geçmiş."""
SUPPORTED_GRID_INTERVALS = ["5m", "15m", "1h", "4h"]
DEFAULT_GRID_BACKTEST_INTERVAL = "15m"
DEFAULT_CAPITAL_USD = 1000.0


def _fetch_candles(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[Candle]:
    raw = get_futures_historical_klines(symbol.upper(), interval, start_ms, end_ms)
    if not raw:
        raise ValueError("Seçilen aralık için mum verisi bulunamadı")
    return [
        Candle(
            open_time_ms=int(k[0]),
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
        )
        for k in raw
    ]


@dataclass
class RangePreview:
    grid_range: GridRange
    candles: list[Candle]
    """Aralığın hesaplandığı mumlar -- fiyat + grid sınırlarını birlikte
    grafikte göstermek (bkz. app.ui.grid_tab) için; range hesaplaması
    sırasında zaten çekildiğinden tekrar ağ isteği gerektirmez."""


def compute_range_for_symbol(
    symbol: str,
    method: str = DEFAULT_RANGE_METHOD,
    interval: str = DEFAULT_RANGE_INTERVAL,
    lookback_candles: int = DEFAULT_RANGE_LOOKBACK_CANDLES,
    **method_kwargs,
) -> RangePreview:
    """Verilen sembol için son `lookback_candles` mumu (`interval` zaman
    diliminde, ör. '4h' veya '1d') çekip seçilen yöntemle (bkz.
    app.grid_trading.range_methods.compute_range) grid üst/alt sınırını
    hesaplar. Kullanılan mumları da (grafikte göstermek için) döner."""
    interval_ms = INTERVAL_MS_MAP[interval]
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - lookback_candles * interval_ms
    candles = _fetch_candles(symbol, interval, start_ms, now_ms)
    grid_range = compute_range(method, candles, **method_kwargs)
    return RangePreview(grid_range=grid_range, candles=candles)


def run_grid_backtest_for_symbol(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str,
    lower_price: float,
    upper_price: float,
    grid_count: int = DEFAULT_GRID_COUNT,
    capital_usd: float = DEFAULT_CAPITAL_USD,
) -> GridBacktestResult:
    """Verilen sembol/tarih aralığı/zaman diliminde geçmiş mum verisini çekip
    grid backtest simülasyonunu çalıştırır (bkz.
    app.grid_trading.grid.run_grid_backtest). Yön stratejilerinin aksine
    indikatör ısınması gerekmez -- grid sınırları ayrıca (bkz.
    compute_range_for_symbol) belirlenip buraya hazır verilir."""
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    if start_ms >= end_ms:
        raise ValueError("Başlangıç tarihi bitiş tarihinden önce olmalı")

    candles = _fetch_candles(symbol, interval, start_ms, end_ms)
    return run_grid_backtest(candles, lower_price, upper_price, grid_count, capital_usd)
