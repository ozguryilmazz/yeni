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


def _wilder_rma(values: list[float], period: int) -> list[float | None]:
    """`values[1:]`'in Wilder RMA'sı (`values[0]` bir önceki mum olmadığı için
    boş/0 placeholder'dır — bkz. atr/adx): ilk `period` değerin (index
    1..period) ortalamasıyla index `period`'da seed'lenir, sonrasında
    (prev*(period-1)+value)/period ile devam eder."""
    n = len(values)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result
    prev = sum(values[1 : period + 1]) / period
    result[period] = prev
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + values[i]) / period
        result[i] = prev
    return result


def adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder'ın ADX'i (TradingView'in varsayılan ADX'iyle aynı yöntem): trendin
    YÖNÜNDEN bağımsız GÜCÜNÜ 0-100 arası ölçer — düşük ADX (ör. <25) yatay/range
    piyasa demektir (grid stratejisinin aradığı rejim), yüksek ADX güçlü trend.

    +DM/-DM (yönlü hareket) ve True Range ayrı ayrı Wilder RMA ile smooth'lanıp
    +DI14/-DI14 üretir; DX = 100×|+DI−(-DI)|/(+DI+(-DI)); ADX ise DX'in
    kendisinin RMA'sıdır. DX, TR/DM'nin ısınması için `period` mum bekler; ADX
    de DX'in ısınması için bir `period` daha bekler — bu yüzden ilk ADX değeri
    ancak yaklaşık 2×period'luk index'te belirir (öncesi None)."""
    n = len(highs)
    if len(lows) != n or len(closes) != n:
        raise ValueError("highs/lows/closes aynı uzunlukta olmalı")

    result: list[float | None] = [None] * n
    if n < 2 * period:
        return result

    true_ranges = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        true_ranges[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0

    smoothed_tr = _wilder_rma(true_ranges, period)
    smoothed_plus_dm = _wilder_rma(plus_dm, period)
    smoothed_minus_dm = _wilder_rma(minus_dm, period)

    dx_values = [0.0] * n
    for i in range(period, n):
        tr_i = smoothed_tr[i]
        if not tr_i:
            continue  # dx_values[i] 0.0 kalır: aralık sıfırsa yön de yok
        plus_di = 100 * smoothed_plus_dm[i] / tr_i
        minus_di = 100 * smoothed_minus_dm[i] / tr_i
        di_sum = plus_di + minus_di
        dx_values[i] = 100 * abs(plus_di - minus_di) / di_sum if di_sum else 0.0

    first_adx_index = 2 * period - 1
    prev = sum(dx_values[period : first_adx_index + 1]) / period
    result[first_adx_index] = prev
    for i in range(first_adx_index + 1, n):
        prev = (prev * (period - 1) + dx_values[i]) / period
        result[i] = prev
    return result


def bollinger_bands(
    closes: list[float], period: int = 20, std_mult: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Bollinger Bantları (TradingView'in varsayılanıyla aynı yöntem): orta bant
    `period`'luk SMA, üst/alt bant bu SMA'nın ±`std_mult` katı POPÜLASYON
    standart sapması (örneklem değil — n'e bölünür, n-1'e değil).

    Döner: (üst, orta, alt) — üçü de ilk `period-1` eleman için None."""
    n = len(closes)
    upper: list[float | None] = [None] * n
    middle: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    if n < period:
        return upper, middle, lower

    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        mean = sum(window) / period
        variance = sum((v - mean) ** 2 for v in window) / period
        std = variance**0.5
        middle[i] = mean
        upper[i] = mean + std_mult * std
        lower[i] = mean - std_mult * std
    return upper, middle, lower
