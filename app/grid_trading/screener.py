import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import httpx

from app.backtest.engine import Candle
from app.backtest.indicators import adx, atr
from app.binance_client import (
    BINANCE_FUTURES_BASE_URL,
    INTERVAL_MS_MAP,
    get_futures_24h_tickers,
    get_futures_historical_klines,
    get_futures_perpetual_symbols,
    get_spot_24h_tickers,
)

DEFAULT_ADX_INTERVAL = "4h"
DEFAULT_ATR_INTERVAL = "1d"
"""ATR volatilite kuralı kullanıcı notlarında açıkça GÜNLÜK grafikte tanımlı;
ADX'ten (4h veya 1D, kullanıcı seçimi) BAĞIMSIZ, sabit bir zaman dilimidir."""
DEFAULT_LOOKBACK_CANDLES = 120
"""ATR(14)/ADX(14) ısınması için yeterden fazla; 4h'de ~20 gün, 1d'de ~4 ay geçmiş."""


@dataclass
class ScreenerCriteria:
    """Grid ticareti için coin uygunluk kriterleri:

    1. Likidite/Hacim (kayma/slippage engeli): 24s işlem hacmi hem spotta hem
       futures'ta belirli bir eşiğin üzerinde olmalı.
    2. Volatilite: günlük ATR(14)/fiyat oranı belirli bir aralıkta olmalı —
       çok düşükse fiyat hareket etmiyor (komisyonu bile çıkaramaz), çok
       yüksekse fiyat grid aralığını kolayca yırtıp geçer.
    3. Trend olmama: ADX(14) (4h veya 1D) belirli bir eşiğin altında olmalı —
       güçlü trendde fiyat gridin bir ucuna dayanıp orada kalır (terste kalma
       riski).
    """

    min_spot_volume_usd: float = 50_000_000.0
    min_futures_volume_usd: float = 200_000_000.0
    atr_pct_min: float = 0.02
    atr_pct_max: float = 0.06
    adx_max: float = 25.0
    atr_period: int = 14
    adx_period: int = 14


@dataclass
class CandidateResult:
    symbol: str
    passes: bool
    spot_volume_usd: float | None
    futures_volume_usd: float | None
    atr_pct: float | None
    adx_value: float | None
    last_price: float | None
    failed_reasons: list[str] = field(default_factory=list)
    """Boşsa tüm kriterleri geçmiştir. Olası değerler: 'spot_volume',
    'futures_volume', 'volatility', 'trend'."""


def evaluate_symbol(
    symbol: str,
    spot_volume_usd: float | None,
    futures_volume_usd: float | None,
    daily_candles: list[Candle],
    adx_candles: list[Candle],
    criteria: ScreenerCriteria | None = None,
) -> CandidateResult:
    """Tek bir sembolü kriterlere göre değerlendirir — saf/test edilebilir
    fonksiyon, ağ çağrısı yapmaz.

    `daily_candles`: GÜNLÜK mumlar — ATR(14)/fiyat oranı kullanıcı kuralı
    gereği HER ZAMAN günlük grafikte hesaplanır. `adx_candles`: ADX'in
    hesaplanacağı zaman diliminde (varsayılan 4 saatlik, bkz.
    DEFAULT_ADX_INTERVAL) mumlar — `daily_candles`'tan BAĞIMSIZ ayrı bir
    seridir (ikisini aynı zaman diliminden hesaplamak ATR%'yi olması
    gerekenden düşük gösterip volatilite kuralını haksız yere elerdi).
    Son elemanların kapanışı 'güncel fiyat' kabul edilir.

    Hacim kriterini geçemeyen semboller için `run_screener` kline verisi hiç
    çekmez (`daily_candles`/`adx_candles` boş geçilir) — bu durumda
    volatilite/trend 'başarısız' değil 'değerlendirilmedi' sayılır, çünkü
    hacim tek başına zaten eler. Hacmi geçip de (ağ hatası gibi bir nedenle)
    verisi eksik kalan semboller ise volatilite/trend'de veri yokluğundan
    başarısız sayılır."""
    criteria = criteria or ScreenerCriteria()
    reasons: list[str] = []

    spot_ok = spot_volume_usd is not None and spot_volume_usd >= criteria.min_spot_volume_usd
    futures_ok = futures_volume_usd is not None and futures_volume_usd >= criteria.min_futures_volume_usd
    if not spot_ok:
        reasons.append("spot_volume")
    if not futures_ok:
        reasons.append("futures_volume")
    volume_ok = spot_ok and futures_ok

    last_price = daily_candles[-1].close if daily_candles else (adx_candles[-1].close if adx_candles else None)

    atr_pct: float | None = None
    if daily_candles and daily_candles[-1].close and len(daily_candles) >= criteria.atr_period + 1:
        daily_highs = [c.high for c in daily_candles]
        daily_lows = [c.low for c in daily_candles]
        daily_closes = [c.close for c in daily_candles]
        last_atr = atr(daily_highs, daily_lows, daily_closes, criteria.atr_period)[-1]
        if last_atr is not None:
            atr_pct = last_atr / daily_candles[-1].close

    adx_value: float | None = None
    if len(adx_candles) >= 2 * criteria.adx_period:
        adx_highs = [c.high for c in adx_candles]
        adx_lows = [c.low for c in adx_candles]
        adx_closes = [c.close for c in adx_candles]
        adx_value = adx(adx_highs, adx_lows, adx_closes, criteria.adx_period)[-1]

    if volume_ok or daily_candles:
        if atr_pct is None or not (criteria.atr_pct_min <= atr_pct <= criteria.atr_pct_max):
            reasons.append("volatility")
    if volume_ok or adx_candles:
        if adx_value is None or adx_value >= criteria.adx_max:
            reasons.append("trend")

    return CandidateResult(
        symbol=symbol,
        passes=not reasons,
        spot_volume_usd=spot_volume_usd,
        futures_volume_usd=futures_volume_usd,
        atr_pct=atr_pct,
        adx_value=adx_value,
        last_price=last_price,
        failed_reasons=reasons,
    )


def run_screener(
    criteria: ScreenerCriteria | None = None,
    adx_interval: str = DEFAULT_ADX_INTERVAL,
    atr_interval: str = DEFAULT_ATR_INTERVAL,
    lookback_candles: int = DEFAULT_LOOKBACK_CANDLES,
) -> list[CandidateResult]:
    """Gerçek Binance verisiyle TÜM USDT-M futures sembollerini tarar:

    1. TEK istekte futures 24s hacmi ve TEK istekte spot 24s hacmi çekilir
       (get_futures_24h_tickers / get_spot_24h_tickers).
    2. Hacim kriterini geçen semboller için (yüzlerce sembolün tamamına kline
       çekmemek adına) İKİ AYRI seri çekilir, paralel isteklerle (bkz.
       get_futures_market_overview'daki thread pool örüntüsü): ATR% için
       `atr_interval` (varsayılan günlük), ADX için `adx_interval`
       (varsayılan 4 saatlik) — ikisi aynıysa (ör. kullanıcı ADX'i de
       günlükten istiyorsa) tekrar ağ isteği atılmaz, aynı veri paylaşılır.

    Sonuç, geçen/geçmeyen TÜM sembolleri (`failed_reasons` ile) içerir —
    listeyi 'sadece uygun olanlar'a indirgemek UI katmanının işidir."""
    criteria = criteria or ScreenerCriteria()

    futures_volumes = {t["symbol"]: float(t.get("quoteVolume", 0.0)) for t in get_futures_24h_tickers()}
    spot_volumes = {t["symbol"]: float(t.get("quoteVolume", 0.0)) for t in get_spot_24h_tickers()}
    perpetual_symbols = get_futures_perpetual_symbols()

    volume_passed = [
        symbol
        for symbol in perpetual_symbols
        if futures_volumes.get(symbol, 0.0) >= criteria.min_futures_volume_usd
        and spot_volumes.get(symbol, 0.0) >= criteria.min_spot_volume_usd
    ]

    daily_candles_by_symbol = _fetch_candles_for_symbols(volume_passed, atr_interval, lookback_candles)
    adx_candles_by_symbol = (
        daily_candles_by_symbol
        if adx_interval == atr_interval
        else _fetch_candles_for_symbols(volume_passed, adx_interval, lookback_candles)
    )

    return [
        evaluate_symbol(
            symbol,
            spot_volumes.get(symbol),
            futures_volumes.get(symbol),
            daily_candles_by_symbol.get(symbol, []),
            adx_candles_by_symbol.get(symbol, []),
            criteria,
        )
        for symbol in perpetual_symbols
    ]


def _fetch_candles_for_symbols(symbols: list[str], interval: str, lookback_candles: int) -> dict[str, list[Candle]]:
    if not symbols:
        return {}

    interval_ms = INTERVAL_MS_MAP[interval]
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - lookback_candles * interval_ms

    candles_by_symbol: dict[str, list[Candle]] = {}
    with httpx.Client(base_url=BINANCE_FUTURES_BASE_URL, timeout=15) as client:
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_symbol = {
                executor.submit(get_futures_historical_klines, symbol, interval, start_ms, now_ms, client): symbol
                for symbol in symbols
            }
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    raw = future.result()
                except Exception:  # noqa: BLE001 - ağ hatası/zaman aşımı olan tek sembol atlanır
                    continue
                candles_by_symbol[symbol] = [
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
    return candles_by_symbol
