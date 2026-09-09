from dataclasses import dataclass

from app.backtest.indicators import atr, ema

# "Esnetilmiş 5D Scalp Stratejisi" parametreleri — yön/giriş EMA9/21/100 + ATR14
# ile belirlenir; SL/TP ise ATR'den değil, o işlemin toplam komisyon maliyetinin
# (giriş+çıkış) katlarından hesaplanır (bkz. _try_open_position).
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
# SL/TP komisyon çarpanları: fiyat mesafesi = mult × 2 × TAKER_FEE_RATE × entry
# (bkz. _try_open_position) — yani mult=10 ~%1.0, mult=20 ~%2.0 uzaklık demektir.
# Düşük çarpanlarda (ör. 2/4) mesafe 15m/1h gibi büyük zaman dilimlerinin tipik
# mum genişliğinin çok altında kalıp çıkışı "hangi eşik daha yakın" gürültüsüne
# teslim ediyordu; 10/20 ile mesafe o gürültüden daha az etkilenecek büyüklüğe
# çıkarılıyor (aynı 1:2 SL:TP oranı korunuyor).
SL_FEE_MULT = 10.0
TP_FEE_MULT = 20.0
# SL=TP simetrik "nötr" test için: iki tarafı da aynı mesafeye koyup entry
# sinyalinin (EMA9/21/100 + ATR bandı) ham yön başarısını, SL/TP mesafesinin
# hangi tarafın daha sık vurulacağını etkilemesinden arındırarak ölçer.
NEUTRAL_FEE_MULT = (SL_FEE_MULT + TP_FEE_MULT) / 2

MARGIN_USD = 2.0
LEVERAGE = 5
STARTING_BALANCE_USD = 100.0
TAKER_FEE_RATE = 0.0005  # Binance USDT-M taker: %0.05


@dataclass
class Candle:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float


@dataclass
class Trade:
    side: str  # "LONG" | "SHORT"
    entry_time_ms: int
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_time_ms: int
    exit_price: float
    exit_reason: str  # "TP" | "SL" | "EOD"
    quantity: float
    gross_pnl_usd: float
    fees_usd: float
    net_pnl_usd: float
    balance_after_usd: float


@dataclass
class BacktestResult:
    trades: list[Trade]
    starting_balance_usd: float
    ending_balance_usd: float
    stopped_early: bool


def run_backtest(
    candles: list[Candle],
    start_time_ms: int,
    reverse: bool = False,
    sl_fee_mult: float = SL_FEE_MULT,
    tp_fee_mult: float = TP_FEE_MULT,
) -> BacktestResult:
    """Verilen mum dizisi üzerinde stratejiyi simüle eder.

    `candles`, indikatörlerin (özellikle EMA100) ısınması için `start_time_ms`'den
    önceki ekstra mumları da içerebilir — indikatörler tüm dizi üzerinden hesaplanır,
    ama yalnızca open_time_ms >= start_time_ms olan mumlarda pozisyon açılır (bkz.
    app.backtest.service).

    Aynı anda tek pozisyon açık tutulur; bir pozisyon TP/SL (veya veri sonunda
    zorunlu kapanış) ile kapanana kadar yeni sinyaller yok sayılır, kapanışın
    olduğu mumda da yeni pozisyon aranmaz.

    `reverse=True` verilirse stratejinin ürettiği yön (LONG/SHORT) tersine
    çevrilir; SL/TP yine aynı mantıkla (komisyon maliyetinin katları) ama yeni
    yöne göre entry fiyatından yeniden hesaplanır — orijinal işlemin
    SL/TP'siyle basitçe yer değiştirmez, çünkü sonraki mumlarda fiyatın nereye
    gideceği bağımsız bir simülasyon gerektirir.

    `sl_fee_mult`/`tp_fee_mult` varsayılan (modül sabiti) dışında bir SL/TP
    komisyon çarpanıyla çalıştırmak için verilebilir — ör. `NEUTRAL_FEE_MULT`
    ile ikisini eşitleyip "nötr" bir test çalıştırmak için.
    """
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    ema_trend = ema(closes, EMA_TREND_PERIOD)
    atr_values = atr(highs, lows, closes, ATR_PERIOD)
    trend_slope = _compute_trend_slope(ema_trend)

    trades: list[Trade] = []
    balance = STARTING_BALANCE_USD
    stopped_early = False
    position: dict | None = None

    for i, candle in enumerate(candles):
        if position is not None:
            side = position["side"]
            sl = position["stop_loss"]
            tp = position["take_profit"]
            hit_sl = candle.low <= sl if side == "LONG" else candle.high >= sl
            hit_tp = candle.high >= tp if side == "LONG" else candle.low <= tp
            is_last_candle = i == len(candles) - 1

            exit_price: float | None = None
            exit_reason: str | None = None
            if hit_sl:
                # Aynı mumda hem TP hem SL bandına girilmiş olsa bile (intrabar tick
                # verisi yok), muhafazakar varsayımla önce SL'in vurulduğu kabul edilir.
                exit_price, exit_reason = sl, "SL"
            elif hit_tp:
                exit_price, exit_reason = tp, "TP"
            elif is_last_candle:
                exit_price, exit_reason = candle.close, "EOD"

            if exit_price is not None:
                trade = _close_position(position, candle.open_time_ms, exit_price, exit_reason, balance)
                trades.append(trade)
                balance = trade.balance_after_usd
                position = None
                continue

        if position is None and candle.open_time_ms >= start_time_ms:
            if (
                ema_fast[i] is None
                or ema_slow[i] is None
                or ema_trend[i] is None
                or atr_values[i] is None
                or trend_slope[i] is None
            ):
                continue
            if balance < MARGIN_USD:
                stopped_early = True
                continue
            position = _try_open_position(
                candle,
                ema_fast[i],
                ema_slow[i],
                ema_trend[i],
                atr_values[i],
                trend_slope[i],
                reverse=reverse,
                sl_fee_mult=sl_fee_mult,
                tp_fee_mult=tp_fee_mult,
            )

    return BacktestResult(
        trades=trades,
        starting_balance_usd=STARTING_BALANCE_USD,
        ending_balance_usd=balance,
        stopped_early=stopped_early,
    )


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


def _try_open_position(
    candle: Candle,
    ema_fast_v: float,
    ema_slow_v: float,
    ema_trend_v: float,
    atr_v: float,
    trend_slope_v: float,
    reverse: bool = False,
    sl_fee_mult: float = SL_FEE_MULT,
    tp_fee_mult: float = TP_FEE_MULT,
) -> dict | None:
    if atr_v <= 0:
        return None

    band_low = min(ema_fast_v, ema_slow_v) - ENTRY_BAND_ATR_MULT * atr_v
    band_high = max(ema_fast_v, ema_slow_v) + ENTRY_BAND_ATR_MULT * atr_v
    if not (band_low <= candle.close <= band_high):
        return None

    min_slope = MIN_TREND_SLOPE_ATR_MULT * atr_v
    is_uptrend = candle.close > ema_trend_v and trend_slope_v >= min_slope
    is_downtrend = candle.close < ema_trend_v and trend_slope_v <= -min_slope

    if is_uptrend:
        side = "SHORT" if reverse else "LONG"
    elif is_downtrend:
        side = "LONG" if reverse else "SHORT"
    else:
        # Yön EMA100'e göre belli ama EMA100'ün kendisi yeterince eğimli değil
        # (yatay/chop piyasa) -> whipsaw riskinden kaçınmak için işlem açılmaz.
        return None

    entry_price = candle.close
    notional_usd = MARGIN_USD * LEVERAGE
    quantity = notional_usd / entry_price

    # Çıkış fiyatı henüz bilinmediğinden çıkış komisyonu da giriş notional'i
    # üzerinden tahmin edilir (SL/TP mesafesi entry'ye yakın olduğundan sapma
    # ihmal edilebilir düzeydedir).
    fee_per_side_usd = notional_usd * TAKER_FEE_RATE
    total_fee_usd = 2 * fee_per_side_usd  # giriş + çıkış
    tp_price_distance = (tp_fee_mult * total_fee_usd) / quantity
    sl_price_distance = (sl_fee_mult * total_fee_usd) / quantity

    if side == "LONG":
        stop_loss = entry_price - sl_price_distance
        take_profit = entry_price + tp_price_distance
    else:
        stop_loss = entry_price + sl_price_distance
        take_profit = entry_price - tp_price_distance

    return {
        "side": side,
        "entry_time_ms": candle.open_time_ms,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "quantity": quantity,
    }


def _close_position(
    position: dict, exit_time_ms: int, exit_price: float, exit_reason: str, balance: float
) -> Trade:
    side = position["side"]
    entry_price = position["entry_price"]
    quantity = position["quantity"]

    if side == "LONG":
        gross_pnl = (exit_price - entry_price) * quantity
    else:
        gross_pnl = (entry_price - exit_price) * quantity

    entry_fee = entry_price * quantity * TAKER_FEE_RATE
    exit_fee = exit_price * quantity * TAKER_FEE_RATE
    fees = entry_fee + exit_fee
    net_pnl = gross_pnl - fees

    return Trade(
        side=side,
        entry_time_ms=position["entry_time_ms"],
        entry_price=entry_price,
        stop_loss=position["stop_loss"],
        take_profit=position["take_profit"],
        exit_time_ms=exit_time_ms,
        exit_price=exit_price,
        exit_reason=exit_reason,
        quantity=quantity,
        gross_pnl_usd=gross_pnl,
        fees_usd=fees,
        net_pnl_usd=net_pnl,
        balance_after_usd=balance + net_pnl,
    )
