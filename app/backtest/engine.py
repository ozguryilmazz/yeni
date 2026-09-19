from collections.abc import Callable
from dataclasses import dataclass

from app.position_sizing import (
    LEVERAGE,
    MARGIN_USD,
    SL_FEE_MULT,
    TAKER_FEE_RATE,
    TP_FEE_MULT,
    compute_position_sizing,
)

STARTING_BALANCE_USD = 100.0


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
    compute_signals: Callable[[list[Candle]], list[str | None]],
    reverse: bool = False,
    sl_fee_mult: float = SL_FEE_MULT,
    tp_fee_mult: float = TP_FEE_MULT,
    margin_usd: float = MARGIN_USD,
    leverage: float = LEVERAGE,
) -> BacktestResult:
    """Verilen mum dizisi üzerinde, `compute_signals` fonksiyonunun ürettiği
    yön sinyallerine göre pozisyon/TP/SL/komisyon simülasyonu yapar.

    Sinyal üretimi tamamen `compute_signals`'a devredilmiştir (bkz.
    app.strategies) — bu fonksiyon hangi stratejinin kullanıldığından
    bağımsızdır, sadece pozisyon açma/kapama/komisyon muhasebesini yönetir.

    `candles`, `compute_signals`'ın kullandığı indikatörlerin (ör. EMA100)
    ısınması için `start_time_ms`'den önceki ekstra mumları da içerebilir —
    sinyaller tüm dizi üzerinden hesaplanır, ama yalnızca open_time_ms >=
    start_time_ms olan mumlarda pozisyon açılır (bkz. app.backtest.service).

    Aynı anda tek pozisyon açık tutulur; bir pozisyon TP/SL (veya veri sonunda
    zorunlu kapanış) ile kapanana kadar yeni sinyaller yok sayılır, kapanışın
    olduğu mumda da yeni pozisyon aranmaz.

    `reverse=True` verilirse stratejinin ürettiği yön (LONG/SHORT) tersine
    çevrilir; SL/TP yine aynı mantıkla (komisyon maliyetinin katları) ama yeni
    yöne göre entry fiyatından yeniden hesaplanır — orijinal işlemin
    SL/TP'siyle basitçe yer değiştirmez, çünkü sonraki mumlarda fiyatın nereye
    gideceği bağımsız bir simülasyon gerektirir.

    `sl_fee_mult`/`tp_fee_mult`/`margin_usd`/`leverage` varsayılan (modül
    sabiti) dışında risk parametreleriyle çalıştırmak için verilebilir — ör.
    `NEUTRAL_FEE_MULT` ile ikisini eşitleyip "nötr" bir test çalıştırmak,
    veya canlı işlem motorunun kullanıcının girdiği risk parametreleriyle
    aynı hesaplamayı yapması için.
    """
    signals = compute_signals(candles)

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
            signal = signals[i]
            if signal is None:
                continue
            if balance < margin_usd:
                stopped_early = True
                continue

            side = signal
            if reverse:
                side = "SHORT" if signal == "LONG" else "LONG"
            entry_price = candle.close
            stop_loss, take_profit, quantity = compute_position_sizing(
                entry_price, side, margin_usd, leverage, sl_fee_mult, tp_fee_mult
            )
            position = {
                "side": side,
                "entry_time_ms": candle.open_time_ms,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "quantity": quantity,
            }

    return BacktestResult(
        trades=trades,
        starting_balance_usd=STARTING_BALANCE_USD,
        ending_balance_usd=balance,
        stopped_early=stopped_early,
    )


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
