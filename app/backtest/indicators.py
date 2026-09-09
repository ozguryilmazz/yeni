def ema(values: list[float], period: int) -> list[float | None]:
    """Klasik (borsa/TradingView) EMA: ilk `period` değerin SMA'sıyla seed'lenir,
    sonrasında k=2/(period+1) ağırlığıyla üstel olarak güncellenir. İlk `period-1`
    eleman için henüz yeterli veri olmadığından None döner."""
    if period <= 0:
        raise ValueError("period pozitif olmalı")

    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result

    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    result[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        result[i] = prev
    return result


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder'ın ATR'si (TradingView'in varsayılan ATR'siyle aynı yöntem): True
    Range'in Wilder smoothing (RMA) ile period'luk ortalaması. İlk mumun bir önceki
    kapanışı olmadığından True Range 2. mumdan itibaren hesaplanabilir; ATR ise en
    erken `period` index'inde (0 tabanlı) belirir, öncesi None'dır."""
    n = len(highs)
    if len(lows) != n or len(closes) != n:
        raise ValueError("highs/lows/closes aynı uzunlukta olmalı")

    result: list[float | None] = [None] * n
    if n < period + 1:
        return result

    true_ranges = [0.0] * n
    for i in range(1, n):
        true_ranges[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    prev = sum(true_ranges[1 : period + 1]) / period
    result[period] = prev
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + true_ranges[i]) / period
        result[i] = prev
    return result
