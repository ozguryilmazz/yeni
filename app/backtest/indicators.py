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


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder'ın RSI'ı (TradingView'in varsayılan RSI'ıyla aynı yöntem):
    ortalama kazanç/kaybın Wilder smoothing (RMA) ile period'luk oranından
    hesaplanan 0-100 arası momentum osilatörü. True Range'de olduğu gibi ilk
    mumun bir önceki kapanışı olmadığından hesap 2. mumdan başlar; RSI ise en
    erken `period` index'inde (0 tabanlı) belirir, öncesi None'dır."""
    n = len(closes)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result

    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        gains[i] = max(change, 0.0)
        losses[i] = max(-change, 0.0)

    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    result[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i] = _rsi_from_averages(avg_gain, avg_loss)
    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
