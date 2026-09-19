from app.backtest.engine import Candle
from app.backtest.indicators import rsi
from app.strategies.base import Strategy

NAME = "Likidite Avı 1m (Equal Highs/Lows + Hacim + RSI Diverjansı)"

LOOKBACK_PERIOD = 20
"""Eşit tepe/dip (equal highs/lows) aranacak mum sayısı."""
EQUAL_LEVEL_TOLERANCE_PCT = 0.0005  # %0.05
"""İki seviyenin 'eşit' sayılması ve sweep'in seviyeyi aştığının kabul
edilmesi için kullanılan yüzde tolerans."""
RSI_PERIOD = 14
RSI_OVERBOUGHT = 65
RSI_OVERSOLD = 35
VOLUME_AVG_WINDOW = 10
VOLUME_SPIKE_MULT = 1.5
MAX_HOLDING_BARS = 10
WARMUP_CANDLES = 60


def compute_signals(candles: list[Candle]) -> list[str | None]:
    """Likidite avı / Swing Failure Pattern sinyali:

    1. Son LOOKBACK_PERIOD mumda eşit tepe (direnç) veya eşit dip (destek)
       seviyesi bulunur (bkz. _find_liquidity_level).
    2. Mevcut mum bu seviyeyi EQUAL_LEVEL_TOLERANCE_PCT kadar aşıp (sweep,
       likidite avı) hacmi son VOLUME_AVG_WINDOW mumun ortalamasının
       VOLUME_SPIKE_MULT katından fazlaysa devam edilir.
    3. Mum seviyenin GERİSİNE kapanmışsa (red/rejection) ve RSI(14) aşırı
       alım/satımdaysa VEYA klasik diverjans gösteriyorsa sinyal onaylanır.

    Sinyal, onay mumunun KENDİ index'ine yazılır (nedensel/causal — sadece o
    ana kadarki veriyi kullanır). Bir sonraki mumun açılışında giriş yapma
    (Strategy.entry_timing='next_open') motorun (hem backtest hem canlı)
    genel sorumluluğudur — strateji bunu kendisi kaydırmaz; canlıda bu,
    onay algılanır algılanmaz anında emir gönderilmesiyle doğal olarak
    sağlanır (bkz. app.live_trading.engine)."""
    n = len(candles)
    closes = [c.close for c in candles]
    volumes = [c.volume for c in candles]
    rsi_values = rsi(closes, RSI_PERIOD)

    signals: list[str | None] = [None] * n
    for i in range(LOOKBACK_PERIOD, n):
        if rsi_values[i] is None or i < VOLUME_AVG_WINDOW:
            continue
        signals[i] = _signal_for_candle(candles, volumes, rsi_values, i)
    return signals


def _signal_for_candle(
    candles: list[Candle], volumes: list[float], rsi_values: list[float | None], i: int
) -> str | None:
    candle = candles[i]
    window_start = i - LOOKBACK_PERIOD
    window_highs = [candles[j].high for j in range(window_start, i)]
    window_lows = [candles[j].low for j in range(window_start, i)]
    rsi_window = [rsi_values[j] for j in range(window_start, i)]

    avg_volume = sum(volumes[i - VOLUME_AVG_WINDOW : i]) / VOLUME_AVG_WINDOW
    if not (avg_volume > 0 and candle.volume > VOLUME_SPIKE_MULT * avg_volume):
        return None

    resistance = _find_liquidity_level(window_highs, EQUAL_LEVEL_TOLERANCE_PCT, "high")
    if (
        resistance is not None
        and candle.high >= resistance * (1 + EQUAL_LEVEL_TOLERANCE_PCT)
        and candle.close < resistance
        and (rsi_values[i] > RSI_OVERBOUGHT or _has_bearish_divergence(window_highs, rsi_window, candle.high, rsi_values[i]))
    ):
        return "SHORT"

    support = _find_liquidity_level(window_lows, EQUAL_LEVEL_TOLERANCE_PCT, "low")
    if (
        support is not None
        and candle.low <= support * (1 - EQUAL_LEVEL_TOLERANCE_PCT)
        and candle.close > support
        and (rsi_values[i] < RSI_OVERSOLD or _has_bullish_divergence(window_lows, rsi_window, candle.low, rsi_values[i]))
    ):
        return "LONG"

    return None


def _find_liquidity_level(values: list[float], tolerance_pct: float, extreme: str) -> float | None:
    """`values` içinde en az 2 elemanın birbirine `tolerance_pct` içinde
    olduğu (eşit tepe/dip) kümeleri bulur; `extreme`='high' ise en yüksek
    kümenin max'ını, 'low' ise en düşük kümenin min'ini döner. Hiç küme
    yoksa None (bu penceredeki tepeler/dipler birbirinden çok farklı,
    belirgin bir likidite seviyesi yok)."""
    best: float | None = None
    for level in values:
        if level == 0:
            continue
        cluster = [v for v in values if abs(v - level) / level <= tolerance_pct]
        if len(cluster) < 2:
            continue
        candidate = max(cluster) if extreme == "high" else min(cluster)
        if best is None or (extreme == "high" and candidate > best) or (extreme == "low" and candidate < best):
            best = candidate
    return best


def _has_bearish_divergence(
    highs_window: list[float], rsi_window: list[float | None], current_high: float, current_rsi: float
) -> bool:
    """Klasik ayı diverjansı: fiyat penceredeki en yüksek RSI'nin olduğu
    mumdan daha yüksek bir tepe (Higher High) yaparken, RSI o mumdan daha
    düşük bir tepe (Lower High) yapmış olmalı."""
    if not rsi_window or any(r is None for r in rsi_window):
        return False
    peak_idx = max(range(len(rsi_window)), key=lambda idx: rsi_window[idx])
    return current_high > highs_window[peak_idx] and current_rsi < rsi_window[peak_idx]


def _has_bullish_divergence(
    lows_window: list[float], rsi_window: list[float | None], current_low: float, current_rsi: float
) -> bool:
    """Klasik boğa diverjansı: fiyat penceredeki en düşük RSI'nin olduğu
    mumdan daha düşük bir dip (Lower Low) yaparken, RSI o mumdan daha
    yüksek bir dip (Higher Low) yapmış olmalı."""
    if not rsi_window or any(r is None for r in rsi_window):
        return False
    trough_idx = min(range(len(rsi_window)), key=lambda idx: rsi_window[idx])
    return current_low < lows_window[trough_idx] and current_rsi > rsi_window[trough_idx]


STRATEGY = Strategy(
    name=NAME,
    compute_signals=compute_signals,
    warmup_candles=WARMUP_CANDLES,
    entry_timing="next_open",
    max_holding_bars=MAX_HOLDING_BARS,
)
