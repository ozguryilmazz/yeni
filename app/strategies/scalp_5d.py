from app.backtest.engine import Candle
from app.backtest.indicators import atr, ema
from app.strategies.base import Strategy

NAME = "Esnetilmiş 5D Scalp (EMA9/21/100 + ATR14)"

EMA_TREND_PERIOD = 100
EMA_FAST_PERIOD = 9
EMA_SLOW_PERIOD = 21
ATR_PERIOD = 14
ENTRY_BAND_ATR_MULT = 0.5
# EMA100'ün yönünü değil eğimini de teyit eder: fiyat EMA100'ün üstünde/altında
# olması tek başına yeterli sayılmaz, EMA100'ün kendisi de TREND_SLOPE_LOOKBACK
# mum önceki değerine göre en az MIN_TREND_SLOPE_ATR_MULT×ATR kadar aynı yönde
# hareket etmiş olmalı — aksi halde piyasa yatay (chop) kabul edilip işlem açılmaz.
TREND_SLOPE_LOOKBACK = 20
MIN_TREND_SLOPE_ATR_MULT = 0.5
# EMA100'ün ilk mumlardaki seed sapmasını azaltmak için işlem aralığından önce
# ekstra ısınma mumu çekilir; bu mumlarda pozisyon açılmaz, yalnızca indikatörleri besler.
WARMUP_CANDLES = EMA_TREND_PERIOD * 3


def compute_signals(candles: list[Candle]) -> list[str | None]:
    """Her mum için 'LONG' / 'SHORT' / None döner: fiyat EMA100 üzerinde ve
    EMA100 yükseliyorsa + fiyat EMA9/EMA21 bölgesine ATR14'ün ±0.5 katı
    toleransla çekilmişse 'LONG'; simetrik koşulda 'SHORT'; aksi halde None."""
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    ema_trend = ema(closes, EMA_TREND_PERIOD)
    atr_values = atr(highs, lows, closes, ATR_PERIOD)
    trend_slope = _compute_trend_slope(ema_trend)

    signals: list[str | None] = [None] * len(candles)
    for i, candle in enumerate(candles):
        if (
            ema_fast[i] is None
            or ema_slow[i] is None
            or ema_trend[i] is None
            or atr_values[i] is None
            or trend_slope[i] is None
        ):
            continue
        signals[i] = _signal_for_candle(
            candle, ema_fast[i], ema_slow[i], ema_trend[i], atr_values[i], trend_slope[i]
        )
    return signals


def _compute_trend_slope(ema_trend: list[float | None]) -> list[float | None]:
    """EMA100'ün TREND_SLOPE_LOOKBACK mum önceki değerine göre ne kadar
    değiştiğini (fiyat biriminde) döner. Pozitif = yükseliyor, negatif =
    düşüyor, sıfıra yakın = yatay (chop). İki ucundan biri hazır değilse None."""
    n = len(ema_trend)
    slope: list[float | None] = [None] * n
    for i in range(TREND_SLOPE_LOOKBACK, n):
        current = ema_trend[i]
        past = ema_trend[i - TREND_SLOPE_LOOKBACK]
        if current is not None and past is not None:
            slope[i] = current - past
    return slope


def _signal_for_candle(
    candle: Candle, ema_fast_v: float, ema_slow_v: float, ema_trend_v: float, atr_v: float, trend_slope_v: float
) -> str | None:
    if atr_v <= 0:
        return None

    band_low = min(ema_fast_v, ema_slow_v) - ENTRY_BAND_ATR_MULT * atr_v
    band_high = max(ema_fast_v, ema_slow_v) + ENTRY_BAND_ATR_MULT * atr_v
    if not (band_low <= candle.close <= band_high):
        return None

    min_slope = MIN_TREND_SLOPE_ATR_MULT * atr_v
    if candle.close > ema_trend_v and trend_slope_v >= min_slope:
        return "LONG"
    if candle.close < ema_trend_v and trend_slope_v <= -min_slope:
        return "SHORT"
    # Yön EMA100'e göre belli ama EMA100'ün kendisi yeterince eğimli değil
    # (yatay/chop piyasa) -> whipsaw riskinden kaçınmak için işlem açılmaz.
    return None


STRATEGY = Strategy(name=NAME, compute_signals=compute_signals, warmup_candles=WARMUP_CANDLES)
