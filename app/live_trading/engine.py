import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.backtest.engine import Candle
from app.binance_client import (
    INTERVAL_MS_MAP,
    cancel_all_futures_open_orders,
    cancel_futures_algo_order,
    get_futures_historical_klines,
    get_futures_open_algo_orders,
    get_futures_position_risk,
    get_futures_symbol_info,
    place_futures_market_order,
    place_futures_stop_loss_order,
    place_futures_take_profit_order,
    round_price_to_tick_size,
    round_quantity_to_lot_size,
    set_futures_leverage,
    set_futures_margin_type,
)
from app.live_trading.kline_stream import KlineStreamListener
from app.position_sizing import compute_position_sizing
from app.strategies.base import Strategy

POSITION_POLL_INTERVAL_SECONDS = 15
POSITION_CLOSED_EPSILON = 1e-9


@dataclass
class RiskParams:
    margin_usd: float
    leverage: int
    sl_fee_mult: float
    tp_fee_mult: float


class LiveTradingEngine:
    """Seçilen strateji + risk parametreleriyle, gerçek Binance Futures
    hesabında otomatik pozisyon açan/kapayan canlı işlem motoru — GERÇEK PARA.

    Bir kline WebSocket akışı dinler; her mum kapanışında stratejinin
    ürettiği sinyali değerlendirir. `mode="confirm"` ise gerçek emir
    göndermeden önce `on_confirmation_needed` ile dışarıya haber verip
    `confirm_and_execute`/`reject_pending_signal` çağrılana kadar bekler;
    `mode="auto"` ise sinyal oluşur oluşmaz anında emir gönderir.

    SL/TP borsa tarafında gerçek STOP_MARKET/TAKE_PROFIT_MARKET
    (closePosition=true) emirleri olarak açılır — bu motor (dolayısıyla
    uygulama) kapansa/çökse bile pozisyon korunur. Pozisyonun ne zaman
    kapandığı periyodik olarak get_futures_position_risk ile kontrol edilir;
    kapandığında hangi taraf (SL/TP) tetiklendiği, borsada hangi emrin hâlâ
    açık olduğuna bakılarak belirlenir ve kalan (tetiklenmeyen) emir iptal
    edilir — Binance bu iki emri birbirine bağlı (OCO) yönetmez, aksi halde
    kalan emir bir sonraki pozisyonda yanlışlıkla tetiklenebilir.

    Aynı anda tek pozisyon açık tutulur; pozisyon açıkken yeni sinyaller
    yok sayılır.

    Strateji `max_holding_bars` tanımlıyorsa (ör. likidite avı stratejisi),
    pozisyon SL/TP'ye değmeden bu kadar mum kapanışı boyunca açık kalırsa
    borsadaki SL/TP emirleri iptal edilip pozisyon piyasa fiyatından
    (reduceOnly) zorla kapatılır ("TIME").

    `Strategy.entry_timing="next_open"` için canlıda ayrı bir kod yolu
    gerekmez: sinyal, onay mumu kapanır kapanmaz algılanıp anında işleme
    konur — bu, gerçek zamanlı olarak zaten "bir sonraki mumun açılışında
    giriş" anlamına gelir. Backtest'te ise bu bekleme app.backtest.engine
    tarafından açıkça simüle edilir.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        symbol: str,
        interval: str,
        strategy: Strategy,
        risk: RiskParams,
        mode: str,
        on_status: Callable[[str], None],
        on_signal: Callable[[str, float], None],
        on_confirmation_needed: Callable[[str, float, float, float], None],
        on_order_placed: Callable[[dict], None],
        on_position_closed: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        if mode not in ("auto", "confirm"):
            raise ValueError("mode 'auto' veya 'confirm' olmalı")

        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol = symbol.upper()
        self.interval = interval
        self.strategy = strategy
        self.risk = risk
        self.mode = mode
        self.on_status = on_status
        self.on_signal = on_signal
        self.on_confirmation_needed = on_confirmation_needed
        self.on_order_placed = on_order_placed
        self.on_position_closed = on_position_closed
        self.on_error = on_error

        self._candles: list[Candle] = []
        self._open_trade: dict | None = None
        self._pending_signal: tuple[str, float] | None = None
        self._symbol_info: dict | None = None

    async def run(self, stop_event: asyncio.Event) -> None:
        self.on_status(f"{self.symbol}: kaldıraç {self.risk.leverage}x ve ISOLATED margin ayarlanıyor…")
        set_futures_leverage(self.api_key, self.api_secret, self.symbol, self.risk.leverage)
        set_futures_margin_type(self.api_key, self.api_secret, self.symbol, "ISOLATED")
        self._symbol_info = get_futures_symbol_info(self.symbol)

        self.on_status("Isınma mumları (geçmiş veri) yükleniyor…")
        self._backfill_candles()
        self.on_status(f"Hazır — {self.symbol} {self.interval} mum kapanışları dinleniyor.")

        listener = KlineStreamListener(self.symbol, self.interval, on_error=self.on_status)
        position_poll_task = asyncio.create_task(self._poll_position_loop(stop_event))
        try:
            await listener.run(stop_event, self._on_candle_closed)
        finally:
            position_poll_task.cancel()
            await asyncio.gather(position_poll_task, return_exceptions=True)

    def _backfill_candles(self) -> None:
        interval_ms = INTERVAL_MS_MAP[self.interval]
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - self.strategy.warmup_candles * interval_ms
        raw = get_futures_historical_klines(self.symbol, self.interval, start_ms, now_ms)
        candles = [
            Candle(
                open_time_ms=int(k[0]),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
            )
            for k in raw
        ]
        # REST'ten dönen son mum henüz kapanmamış (an itibarıyla oluşan) olabilir;
        # gerçek kapanışı WebSocket'ten (x=true) bekleriz, o yüzden burada atılır.
        if candles:
            candles.pop()
        self._candles = candles

    def _on_candle_closed(self, candle: Candle) -> None:
        self._candles.append(candle)

        if self._open_trade is not None:
            if self.strategy.max_holding_bars is not None:
                self._open_trade["bars_since_entry"] += 1
                if self._open_trade["bars_since_entry"] >= self.strategy.max_holding_bars:
                    self._force_close_on_timeout()
            return  # pozisyon açıkken yeni sinyal aranmaz

        signals = self.strategy.compute_signals(self._candles)
        signal = signals[-1]
        if signal is None:
            return

        self.on_signal(signal, candle.close)

        if self.mode == "confirm":
            self._pending_signal = (signal, candle.close)
            try:
                stop_loss, take_profit, _ = compute_position_sizing(
                    candle.close, signal, self.risk.margin_usd, self.risk.leverage,
                    self.risk.sl_fee_mult, self.risk.tp_fee_mult,
                )
            except Exception:  # noqa: BLE001 - önizleme başarısız olsa da onay isteği iletilsin
                stop_loss = take_profit = candle.close
            self.on_confirmation_needed(signal, candle.close, stop_loss, take_profit)
            return

        self._execute_signal(signal, candle.close)

    def confirm_and_execute(self) -> None:
        """GUI'de 'Onayla' ile çağrılır (yalnızca mode='confirm'). Bekleyen bir
        sinyal yoksa (ör. zaman aşımına uğradı veya zaten işlendi) hiçbir şey
        yapmaz."""
        if self._pending_signal is None:
            return
        signal, price = self._pending_signal
        self._pending_signal = None
        self._execute_signal(signal, price)

    def reject_pending_signal(self) -> None:
        """GUI'de 'Reddet' ile çağrılır (yalnızca mode='confirm')."""
        if self._pending_signal is not None:
            self._pending_signal = None
            self.on_status("Sinyal reddedildi, gerçek emir gönderilmedi.")

    def _execute_signal(self, signal: str, reference_price: float) -> None:
        try:
            stop_loss, take_profit, quantity = compute_position_sizing(
                reference_price, signal, self.risk.margin_usd, self.risk.leverage,
                self.risk.sl_fee_mult, self.risk.tp_fee_mult,
            )
            quantity = round_quantity_to_lot_size(self._symbol_info, quantity)
            stop_loss = round_price_to_tick_size(self._symbol_info, stop_loss)
            take_profit = round_price_to_tick_size(self._symbol_info, take_profit)
            if quantity <= 0:
                self.on_error(
                    f"Hesaplanan miktar borsanın minimum lot büyüklüğünün altında (margin/kaldıraç çok "
                    f"düşük olabilir), emir gönderilmedi."
                )
                return

            entry_side = "BUY" if signal == "LONG" else "SELL"
            exit_side = "SELL" if signal == "LONG" else "BUY"

            self.on_status(f"{signal} girişi gönderiliyor: {quantity} {self.symbol} @ piyasa")
            entry_order = place_futures_market_order(self.api_key, self.api_secret, self.symbol, entry_side, quantity)
        except Exception as exc:  # noqa: BLE001 - gerçek para emri hatası; kullanıcıya iletilmeli
            self.on_error(f"Emir gönderilemedi: {exc}")
            return

        # Giriş emri borsada GERÇEKLEŞTİ -- pozisyon artık gerçek ve açık.
        # Buradan sonra SL/TP yerleştirmede bir hata olsa bile pozisyonu
        # `_open_trade`'e yazıp izlemeye devam etmeliyiz; aksi halde uygulama
        # bu gerçek ve koruma emri olmayan pozisyondan tamamen habersiz kalır
        # (bkz. _poll_position_loop -- yalnızca _open_trade doluyken çalışır).
        self._open_trade = {
            "side": signal,
            "entry_price": reference_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "quantity": quantity,
            "entry_order_id": entry_order.get("orderId"),
            "sl_order_id": None,
            "tp_order_id": None,
            "bars_since_entry": 0,
        }

        try:
            sl_order = place_futures_stop_loss_order(self.api_key, self.api_secret, self.symbol, exit_side, stop_loss)
            tp_order = place_futures_take_profit_order(
                self.api_key, self.api_secret, self.symbol, exit_side, take_profit
            )
            self._open_trade["sl_order_id"] = sl_order.get("algoId")
            self._open_trade["tp_order_id"] = tp_order.get("algoId")
        except Exception as exc:  # noqa: BLE001 - pozisyon açık ama korumasız kaldı; kullanıcı ACİLEN bilmeli
            self.on_error(
                f"POZİSYON AÇILDI AMA SL/TP EMRİ GÖNDERİLEMEDİ: {exc}. Pozisyon şu an borsada "
                f"KORUMASIZ açık — Binance uygulamasından/sitesinden manuel kontrol edin."
            )

        self.on_order_placed(dict(self._open_trade))

    def _force_close_on_timeout(self) -> None:
        """Strateji `max_holding_bars` tanımlıyorsa ve pozisyon SL/TP'ye
        değmeden bu kadar mum boyunca açık kaldıysa, borsadaki SL/TP
        emirlerini iptal edip pozisyonu piyasa fiyatından (reduceOnly)
        kapatır."""
        trade = self._open_trade
        self.on_status(
            f"Maksimum bekleme süresi ({self.strategy.max_holding_bars} mum) doldu, "
            f"pozisyon piyasa fiyatından kapatılıyor."
        )
        try:
            cancel_all_futures_open_orders(self.api_key, self.api_secret, self.symbol)
            self._cancel_algo_order_safely(trade["sl_order_id"])
            self._cancel_algo_order_safely(trade["tp_order_id"])
            exit_side = "SELL" if trade["side"] == "LONG" else "BUY"
            place_futures_market_order(
                self.api_key, self.api_secret, self.symbol, exit_side, trade["quantity"], reduce_only=True
            )
        except Exception as exc:  # noqa: BLE001 - gerçek para emri hatası; kullanıcıya iletilmeli
            self.on_error(f"Zaman aşımı kapatma emri gönderilemedi: {exc}")
            return
        self._open_trade = None
        self.on_position_closed("TIME")

    async def _poll_position_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POSITION_POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
            if self._open_trade is not None:
                self._check_position_closed()

    def _check_position_closed(self) -> None:
        try:
            positions = get_futures_position_risk(self.api_key, self.api_secret, self.symbol)
        except Exception as exc:  # noqa: BLE001
            self.on_status(f"Pozisyon durumu sorgulanamadı, tekrar denenecek: {exc}")
            return

        position_amt = float(positions[0]["positionAmt"]) if positions else 0.0
        if abs(position_amt) > POSITION_CLOSED_EPSILON:
            return  # pozisyon hâlâ açık

        trade = self._open_trade
        self._open_trade = None

        try:
            open_orders = get_futures_open_algo_orders(self.api_key, self.api_secret, self.symbol)
        except Exception as exc:  # noqa: BLE001
            open_orders = []
            self.on_status(f"Açık emirler sorgulanamadı: {exc}")

        open_algo_ids = {o.get("algoId") for o in open_orders}
        sl_still_open = trade["sl_order_id"] in open_algo_ids
        tp_still_open = trade["tp_order_id"] in open_algo_ids

        if tp_still_open and not sl_still_open:
            exit_reason = "SL"
            self._cancel_algo_order_safely(trade["tp_order_id"])
        elif sl_still_open and not tp_still_open:
            exit_reason = "TP"
            self._cancel_algo_order_safely(trade["sl_order_id"])
        else:
            exit_reason = "UNKNOWN"

        self.on_position_closed(exit_reason)

    def _cancel_algo_order_safely(self, algo_id: object) -> None:
        if algo_id is None:
            return
        try:
            cancel_futures_algo_order(self.api_key, self.api_secret, self.symbol, algo_id)
        except Exception as exc:  # noqa: BLE001 - emir zaten kapanmış/geçersiz olabilir, kritik değil
            self.on_status(f"Kalan koruma emri iptal edilemedi (muhtemelen zaten kapanmış): {exc}")
