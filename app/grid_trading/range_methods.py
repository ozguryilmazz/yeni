from dataclasses import dataclass, field

from app.backtest.engine import Candle
from app.backtest.indicators import atr, bollinger_bands

DEFAULT_TOLERANCE_PCT = 0.005  # %0.5 -- iki tepe/dibin 'eşit' sayılması için tolerans
DEFAULT_MARGIN_PCT = 0.015  # %1.5 -- seviyenin ötesine bırakılan pay
DEFAULT_MIN_TOUCHES = 2


@dataclass
class GridRange:
    method: str
    lower_price: float
    upper_price: float
    details: dict = field(default_factory=dict)
    """Yönteme özgü ek bilgi (UI'da gösterim/hata ayıklama için) -- ör.
    kullanılan destek/direnç seviyesi ve dokunuş sayısı, Bollinger orta
    bandı, ATR değeri."""


def _cluster_levels(values: list[float], tolerance_pct: float) -> list[tuple[float, int]]:
    """`values` içinde birbirine `tolerance_pct` kadar yakın değerleri aynı
    seviye sayıp kümeler (bkz. app.strategies.liquidity_sweep_1m'deki eşit
    tepe/dip kümelemesinin genellenmiş hâli); her küme için (küme ortalaması,
    dokunuş sayısı) döner."""
    clusters: list[list[float]] = []
    for value in sorted(values):
        if clusters and clusters[-1][-1] > 0 and abs(value - clusters[-1][-1]) / clusters[-1][-1] <= tolerance_pct:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [(sum(c) / len(c), len(c)) for c in clusters]


def support_resistance_range(
    candles: list[Candle],
    min_touches: int = DEFAULT_MIN_TOUCHES,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    margin_pct: float = DEFAULT_MARGIN_PCT,
) -> GridRange:
    """Metot 1 (önerilen): fiyatın en az `min_touches` kez test ettiği ana
    destek/direnç seviyelerini bulur; direncin `margin_pct` üstünü üst sınır,
    desteğin `margin_pct` altını alt sınır yapar.

    Birbirine `tolerance_pct` kadar yakın tepe/dipler aynı seviye sayılır
    (bkz. _cluster_levels); yeterli dokunuşu (>= min_touches) alan kümeler
    arasından EN ÇOK dokunulan 'ana' seviye seçilir. Hiçbir küme eşiği
    geçemezse (ör. çok kısa/tek yönlü bir pencere), pencerenin ham en
    yüksek/en düşük değerine düşülür -- bu durum details'te
    resistance_fallback/support_fallback=True ile işaretlenir, çünkü bu daha
    az güvenilir bir sınırdır."""
    if not candles:
        raise ValueError("Aralık hesaplamak için en az bir mum gerekli")

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    resistance_clusters = [c for c in _cluster_levels(highs, tolerance_pct) if c[1] >= min_touches]
    support_clusters = [c for c in _cluster_levels(lows, tolerance_pct) if c[1] >= min_touches]

    resistance_fallback = not resistance_clusters
    support_fallback = not support_clusters
    resistance_level, resistance_touches = (
        max(resistance_clusters, key=lambda item: item[1]) if resistance_clusters else (max(highs), 1)
    )
    support_level, support_touches = (
        max(support_clusters, key=lambda item: item[1]) if support_clusters else (min(lows), 1)
    )

    upper_price = resistance_level * (1 + margin_pct)
    lower_price = support_level * (1 - margin_pct)
    if lower_price >= upper_price:
        raise ValueError("Hesaplanan alt sınır üst sınırdan küçük olmalı (veri yetersiz/tutarsız olabilir)")

    return GridRange(
        method="support_resistance",
        lower_price=lower_price,
        upper_price=upper_price,
        details={
            "resistance_level": resistance_level,
            "resistance_touches": resistance_touches,
            "resistance_fallback": resistance_fallback,
            "support_level": support_level,
            "support_touches": support_touches,
            "support_fallback": support_fallback,
            "margin_pct": margin_pct,
            "tolerance_pct": tolerance_pct,
            "min_touches": min_touches,
        },
    )


def bollinger_range(candles: list[Candle], period: int = 20, std_mult: float = 2.0) -> GridRange:
    """Metot 2: Bollinger Bantları(`period`, `std_mult`) üst/alt bandı
    doğrudan grid üst/alt sınırı olur -- piyasanın o anki volatilite
    genişliğine göre dinamik bir aralık. `candles` günlük veya 4 saatlik
    mumlar olmalıdır; son mumun bandı kullanılır."""
    closes = [c.close for c in candles]
    upper, middle, lower = bollinger_bands(closes, period, std_mult)
    if not closes or upper[-1] is None:
        raise ValueError(f"Bollinger Bantları için en az {period} mum gerekli")

    return GridRange(
        method="bollinger",
        lower_price=lower[-1],
        upper_price=upper[-1],
        details={"period": period, "std_mult": std_mult, "middle": middle[-1]},
    )


def atr_range(candles: list[Candle], k: float = 3.0, period: int = 14) -> GridRange:
    """Metot 3: mevcut fiyat ± k×ATR(`period`) -- oynaklığa dayalı
    istatistiksel bant. k=2-3 kısa vadeli/sık işlemli (1-3 gün, dar aralık)
    grid, k=5-6 orta vadeli (1-4 hafta, geniş aralık) grid için tipiktir;
    kesin değer kullanıcı tercihine bırakılmıştır."""
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    atr_values = atr(highs, lows, closes, period)
    if not closes or atr_values[-1] is None:
        raise ValueError(f"ATR({period}) için en az {period + 1} mum gerekli")

    current_price = closes[-1]
    current_atr = atr_values[-1]
    return GridRange(
        method="atr",
        lower_price=current_price - k * current_atr,
        upper_price=current_price + k * current_atr,
        details={"k": k, "period": period, "current_price": current_price, "atr": current_atr},
    )


RANGE_METHODS = {
    "support_resistance": support_resistance_range,
    "bollinger": bollinger_range,
    "atr": atr_range,
}
RANGE_METHOD_LABELS = {
    "support_resistance": "Destek/Direnç (önerilen)",
    "bollinger": "Bollinger Bantları (20, 2)",
    "atr": "ATR Çarpanı",
}
DEFAULT_RANGE_METHOD = "support_resistance"


def compute_range(method: str, candles: list[Candle], **kwargs) -> GridRange:
    try:
        func = RANGE_METHODS[method]
    except KeyError:
        raise ValueError(f"Bilinmeyen aralık metodu: {method}") from None
    return func(candles, **kwargs)
