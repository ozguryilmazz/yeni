import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import httpx

from app.backtest.engine import Candle
from app.backtest.indicators import adx, atr, bollinger_bands, rsi
from app.binance_client import (
    BINANCE_FUTURES_BASE_URL,
    INTERVAL_MS_MAP,
    get_futures_24h_tickers,
    get_futures_historical_klines,
    get_futures_perpetual_symbols,
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

    1. Likidite/Hacim (kayma/slippage engeli): 24s USDT-M futures işlem hacmi
       belirli bir eşiğin üzerinde olmalı. Çok yüksek tutmak sadece zaten
       trend halindeki büyük coinleri yakalar; 30M-100M$ arası ideal kabul
       edilir (üst sınır zorunlu değildir, sadece varsayılan alt eşik budur).
    2. Trend olmama (yatay piyasayı doğrulama): 4 saatlik ADX(14) belirli bir
       eşiğin altında olmalı VE günlük Bollinger Bantları fiyatın ya bandın
       ORTASINDA olduğunu ya da bantların YATAY SIKIŞMADA (dar bant genişliği)
       olduğunu doğrulamalı — ikisi de güçlü bir trendin/kırılımın henüz
       başlamadığını gösterir.
    3. Dengeli volatilite: günlük ATR(14)/fiyat oranı belirli bir aralıkta
       olmalı — çok düşükse fiyat hareket etmiyor (komisyonu bile çıkaramaz),
       çok yüksekse fiyat grid aralığını kolayca yırtıp geçer.
    4. Aşırı alım/satım kontrolü: 4 saatlik RSI(14) dengeli bir bölgede
       olmalı — kırılım eşiğine yakın (aşırı şişmiş/aşırı satılmış) coinler
       elenir.
    """

    min_futures_volume_usd: float = 30_000_000.0
    atr_pct_min: float = 0.015
    atr_pct_max: float = 0.045
    adx_max: float = 28.0
    rsi_min: float = 40.0
    rsi_max: float = 60.0
    bollinger_percent_b_min: float = 0.25
    """Fiyatın bant içindeki konumu ('%B'): (kapanış-alt bant)/(üst bant-alt
    bant). 0.5 tam ortada demektir. Bu iki sınır 'bandın ortası'nı bandın orta
    yarısı (%25-%75) olarak tanımlar."""
    bollinger_percent_b_max: float = 0.75
    bollinger_bandwidth_squeeze_max: float = 0.10
    """Bant genişliği (üst bant-alt bant)/orta bant oranı bu değerin altındaysa
    'yatay sıkışma' (squeeze) kabul edilir — bandın kendisi zaten dar demektir,
    fiyatın bant içindeki konumundan bağımsız olarak geçerli sayılır."""
    atr_period: int = 14
    adx_period: int = 14
    rsi_period: int = 14
    bollinger_period: int = 20
    bollinger_std_mult: float = 2.0


@dataclass
class CandidateResult:
    symbol: str
    passes: bool
    futures_volume_usd: float | None
    atr_pct: float | None
    adx_value: float | None
    rsi_value: float | None
    bollinger_percent_b: float | None
    bollinger_bandwidth: float | None
    last_price: float | None
    failed_reasons: list[str] = field(default_factory=list)
    """Boşsa tüm kriterleri geçmiştir. Olası değerler: 'futures_volume',
    'volatility', 'bollinger', 'trend', 'rsi'."""


def evaluate_symbol(
    symbol: str,
    futures_volume_usd: float | None,
    daily_candles: list[Candle],
    adx_candles: list[Candle],
    criteria: ScreenerCriteria | None = None,
) -> CandidateResult:
    """Tek bir sembolü kriterlere göre değerlendirir — saf/test edilebilir
    fonksiyon, ağ çağrısı yapmaz.

    `daily_candles`: GÜNLÜK mumlar — ATR(14)/fiyat oranı VE Bollinger Bantları
    kullanıcı kuralı gereği HER ZAMAN günlük grafikte hesaplanır. `adx_candles`:
    ADX'in (ve RSI'ın) hesaplanacağı zaman diliminde (varsayılan 4 saatlik,
    bkz. DEFAULT_ADX_INTERVAL) mumlar — `daily_candles`'tan BAĞIMSIZ ayrı bir
    seridir (ikisini aynı zaman diliminden hesaplamak ATR%'yi olması
    gerekenden düşük gösterip volatilite kuralını haksız yere elerdi).
    Son elemanların kapanışı 'güncel fiyat' kabul edilir.

    Hacim kriterini geçemeyen semboller için `run_screener` kline verisi hiç
    çekmez (`daily_candles`/`adx_candles` boş geçilir) — bu durumda diğer
    kriterler 'başarısız' değil 'değerlendirilmedi' sayılır, çünkü hacim tek
    başına zaten eler. Hacmi geçip de (ağ hatası gibi bir nedenle) verisi
    eksik kalan semboller ise ilgili kriterlerde veri yokluğundan başarısız
    sayılır."""
    criteria = criteria or ScreenerCriteria()
    reasons: list[str] = []

    volume_ok = futures_volume_usd is not None and futures_volume_usd >= criteria.min_futures_volume_usd
    if not volume_ok:
        reasons.append("futures_volume")

    last_price = daily_candles[-1].close if daily_candles else (adx_candles[-1].close if adx_candles else None)

    atr_pct: float | None = None
    if daily_candles and daily_candles[-1].close and len(daily_candles) >= criteria.atr_period + 1:
        daily_highs = [c.high for c in daily_candles]
        daily_lows = [c.low for c in daily_candles]
        daily_closes = [c.close for c in daily_candles]
        last_atr = atr(daily_highs, daily_lows, daily_closes, criteria.atr_period)[-1]
        if last_atr is not None:
            atr_pct = last_atr / daily_candles[-1].close

    bollinger_percent_b: float | None = None
    bollinger_bandwidth: float | None = None
    if daily_candles and len(daily_candles) >= criteria.bollinger_period:
        daily_closes = [c.close for c in daily_candles]
        upper, middle, lower = bollinger_bands(daily_closes, criteria.bollinger_period, criteria.bollinger_std_mult)
        band_upper, band_middle, band_lower = upper[-1], middle[-1], lower[-1]
        if band_upper is not None and band_lower is not None and band_middle and band_upper > band_lower:
            bollinger_percent_b = (daily_candles[-1].close - band_lower) / (band_upper - band_lower)
            bollinger_bandwidth = (band_upper - band_lower) / band_middle

    adx_value: float | None = None
    if len(adx_candles) >= 2 * criteria.adx_period:
        adx_highs = [c.high for c in adx_candles]
        adx_lows = [c.low for c in adx_candles]
        adx_closes = [c.close for c in adx_candles]
        adx_value = adx(adx_highs, adx_lows, adx_closes, criteria.adx_period)[-1]

    rsi_value: float | None = None
    if len(adx_candles) >= criteria.rsi_period + 1:
        rsi_value = rsi([c.close for c in adx_candles], criteria.rsi_period)[-1]

    if volume_ok or daily_candles:
        if atr_pct is None or not (criteria.atr_pct_min <= atr_pct <= criteria.atr_pct_max):
            reasons.append("volatility")
        bollinger_ok = bollinger_percent_b is not None and (
            criteria.bollinger_percent_b_min <= bollinger_percent_b <= criteria.bollinger_percent_b_max
            or (bollinger_bandwidth is not None and bollinger_bandwidth <= criteria.bollinger_bandwidth_squeeze_max)
        )
        if not bollinger_ok:
            reasons.append("bollinger")
    if volume_ok or adx_candles:
        if adx_value is None or adx_value >= criteria.adx_max:
            reasons.append("trend")
        if rsi_value is None or not (criteria.rsi_min <= rsi_value <= criteria.rsi_max):
            reasons.append("rsi")

    return CandidateResult(
        symbol=symbol,
        passes=not reasons,
        futures_volume_usd=futures_volume_usd,
        atr_pct=atr_pct,
        adx_value=adx_value,
        rsi_value=rsi_value,
        bollinger_percent_b=bollinger_percent_b,
        bollinger_bandwidth=bollinger_bandwidth,
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

    1. TEK istekte futures 24s hacmi çekilir (get_futures_24h_tickers).
    2. Hacim kriterini geçen semboller için (yüzlerce sembolün tamamına kline
       çekmemek adına) İKİ AYRI seri çekilir, paralel isteklerle (bkz.
       get_futures_market_overview'daki thread pool örüntüsü): ATR%/Bollinger
       için `atr_interval` (varsayılan günlük), ADX/RSI için `adx_interval`
       (varsayılan 4 saatlik) — ikisi aynıysa (ör. kullanıcı ADX'i de
       günlükten istiyorsa) tekrar ağ isteği atılmaz, aynı veri paylaşılır.

    Sonuç, geçen/geçmeyen TÜM sembolleri (`failed_reasons` ile) içerir —
    listeyi 'sadece uygun olanlar'a indirgemek UI katmanının işidir."""
    criteria = criteria or ScreenerCriteria()

    futures_volumes = {t["symbol"]: float(t.get("quoteVolume", 0.0)) for t in get_futures_24h_tickers()}
    perpetual_symbols = get_futures_perpetual_symbols()

    volume_passed = [
        symbol for symbol in perpetual_symbols if futures_volumes.get(symbol, 0.0) >= criteria.min_futures_volume_usd
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
