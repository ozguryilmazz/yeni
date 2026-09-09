from dataclasses import dataclass

from app.backtest.indicators import atr, ema

# "Esnetilmiş 5D Scalp Stratejisi" parametreleri
EMA_TREND_PERIOD = 100
EMA_FAST_PERIOD = 9
EMA_SLOW_PERIOD = 21
ATR_PERIOD = 14
ENTRY_BAND_ATR_MULT = 0.5
SL_ATR_MULT = 1.0
TP_ATR_MULT = 2.0

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


def run_backtest(candles: list[Candle], start_time_ms: int, reverse: bool = False) -> BacktestResult:
    """Verilen mum dizisi üzerinde stratejiyi simüle eder.

    `candles`, indikatörlerin (özellikle EMA100) ısınması için `start_time_ms`'den
    önceki ekstra mumları da içerebilir — indikatörler tüm dizi üzerinden hesaplanır,
    ama yalnızca open_time_ms >= start_time_ms olan mumlarda pozisyon açılır (bkz.
    app.backtest.service).

    Aynı anda tek pozisyon açık tutulur; bir pozisyon TP/SL (veya veri sonunda
    zorunlu kapanış) ile kapanana kadar yeni sinyaller yok sayılır, kapanışın
    olduğu mumda da yeni pozisyon aranmaz.

    `reverse=True` verilirse stratejinin ürettiği yön (LONG/SHORT) tersine
    çevrilir; SL/TP yine aynı mantıkla (1×ATR / 2×ATR) ama yeni yöne göre
    entry fiyatından yeniden hesaplanır — orijinal işlemin SL/TP'siyle basitçe
    yer değiştirmez, çünkü sonraki mumlarda fiyatın nereye gideceği bağımsız
    bir simülasyon gerektirir.
    """
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    ema_trend = ema(closes, EMA_TREND_PERIOD)
    atr_values = atr(highs, lows, closes, ATR_PERIOD)

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
            if ema_fast[i] is None or ema_slow[i] is None or ema_trend[i] is None or atr_values[i] is None:
                continue
            if balance < MARGIN_USD:
                stopped_early = True
                continue
            position = _try_open_position(
                candle, ema_fast[i], ema_slow[i], ema_trend[i], atr_values[i], reverse=reverse
            )

    return BacktestResult(
        trades=trades,
        starting_balance_usd=STARTING_BALANCE_USD,
        ending_balance_usd=balance,
        stopped_early=stopped_early,
    )


def _try_open_position(
    candle: Candle,
    ema_fast_v: float,
    ema_slow_v: float,
    ema_trend_v: float,
    atr_v: float,
    reverse: bool = False,
) -> dict | None:
    if atr_v <= 0:
        return None

    band_low = min(ema_fast_v, ema_slow_v) - ENTRY_BAND_ATR_MULT * atr_v
    band_high = max(ema_fast_v, ema_slow_v) + ENTRY_BAND_ATR_MULT * atr_v
    if not (band_low <= candle.close <= band_high):
        return None

    if candle.close > ema_trend_v:
        side = "SHORT" if reverse else "LONG"
    elif candle.close < ema_trend_v:
        side = "LONG" if reverse else "SHORT"
    else:
        return None

    entry_price = candle.close
    if side == "LONG":
        stop_loss = entry_price - SL_ATR_MULT * atr_v
        take_profit = entry_price + TP_ATR_MULT * atr_v
    else:
        stop_loss = entry_price + SL_ATR_MULT * atr_v
        take_profit = entry_price - TP_ATR_MULT * atr_v

    notional_usd = MARGIN_USD * LEVERAGE
    quantity = notional_usd / entry_price

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
