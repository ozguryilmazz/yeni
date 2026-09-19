TAKER_FEE_RATE = 0.0005  # Binance USDT-M taker: %0.05

MARGIN_USD = 2.0
LEVERAGE = 5
# SL/TP komisyon çarpanları: fiyat mesafesi = mult × 2 × TAKER_FEE_RATE × entry
# (bkz. compute_position_sizing) — yani mult=10 ~%1.0, mult=20 ~%2.0 uzaklık demektir.
SL_FEE_MULT = 10.0
TP_FEE_MULT = 20.0
# SL=TP simetrik "nötr" test için: iki tarafı da aynı mesafeye koyup entry
# sinyalinin ham yön başarısını, SL/TP mesafesinin hangi tarafın daha sık
# vurulacağını etkilemesinden arındırarak ölçer (bkz. app.backtest.service).
NEUTRAL_FEE_MULT = (SL_FEE_MULT + TP_FEE_MULT) / 2


def compute_position_sizing(
    entry_price: float,
    side: str,
    margin_usd: float = MARGIN_USD,
    leverage: float = LEVERAGE,
    sl_fee_mult: float = SL_FEE_MULT,
    tp_fee_mult: float = TP_FEE_MULT,
) -> tuple[float, float, float]:
    """SL/TP fiyat seviyelerini ve pozisyon miktarını hesaplar.

    Backtest simülasyonu (app.backtest.engine) ve canlı işlem motoru bu
    fonksiyonu ORTAK kullanır ki aralarında tutarsızlık olmasın — backtest'te
    "ne olurdu" diye simüle edilen SL/TP, canlıda borsaya gönderilen gerçek
    STOP_MARKET/TAKE_PROFIT_MARKET seviyeleriyle birebir aynı formülden gelir.

    SL/TP mesafesi, o işlemin toplam (giriş+çıkış) komisyon maliyetinin
    katları olarak hesaplanır — ATR veya volatiliteden bağımsızdır. Çıkış
    fiyatı henüz bilinmediğinden çıkış komisyonu da giriş notional'i üzerinden
    tahmin edilir (SL/TP mesafesi entry'ye yakın olduğundan sapma ihmal
    edilebilir düzeydedir).

    Döner: (stop_loss, take_profit, quantity)
    """
    notional_usd = margin_usd * leverage
    quantity = notional_usd / entry_price

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

    return stop_loss, take_profit, quantity
