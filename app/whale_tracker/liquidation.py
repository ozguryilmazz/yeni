import asyncio
import json
import time
from collections import deque
from collections.abc import Callable

from app.whale_tracker.models import ModuleSignal

LIQUIDATION_STREAM_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
"""Binance Futures 'All Market Liquidation Order' stream'i — TÜM sembollerdeki anlık
zorunlu likidasyon (forceOrder) event'lerini tek bir bağlantıdan yayınlar. Her mesaj
'@arr' isminin aksine TEK bir forceOrder event objesidir (dizi değil)."""


class LiquidationTracker:
    """Modül C (mantık kısmı) — son `window_seconds` içindeki likidasyon hacmini
    (USDT) pozisyon yönüne göre toplar.

    Binance forceOrder event'inde `S` (side) alanı, LİKİDE OLAN EMRİN yönüdür —
    pozisyonun tersidir: bir LONG pozisyon zorla kapatılırken emir SELL olarak
    girilir, bir SHORT pozisyon zorla kapatılırken emir BUY olarak girilir. Yani:
      - side == "SELL"  -> likide olan pozisyon LONG'du
      - side == "BUY"   -> likide olan pozisyon SHORT'tu

    Kullanıcının kuralı "batan yönün TERSİNE tetik sinyali" ise: LONG pozisyonlar
    toplu likide oluyorsa sinyal SHORT; SHORT pozisyonlar toplu likide oluyorsa
    sinyal LONG'dur (short squeeze zaten yukarı bir hareket yaratıyor, buna
    'katılma' sinyali).
    """

    def __init__(self, window_seconds: float = 60, threshold_usdt: float = 1_000_000) -> None:
        self.window_seconds = window_seconds
        self.threshold_usdt = threshold_usdt
        self._events: deque[tuple[float, str, float]] = deque()  # (ts, side, usdt_value)

    def update_threshold(self, threshold_usdt: float) -> None:
        """Eşiği dışarıdan (ör. sembolün 24s hacminin bir yüzdesi olarak) günceller.
        Sabit 1M USDT, hacmi düşük bir altcoin için devasa ama BTC için sıradan bir
        gürültü olabileceğinden, engine bunu her REST poll döngüsünde dinamik olarak
        çağırır (bkz. WhaleTrapEngine.poll_once)."""
        self.threshold_usdt = threshold_usdt

    def add_liquidation(self, side: str, quantity: float, price: float, timestamp: float | None = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        usdt_value = quantity * price
        self._events.append((ts, side, usdt_value))
        self._trim(ts)

    def _trim(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def evaluate(self) -> ModuleSignal:
        # Pencereyi son eklenen event'in zaman damgasına göre kırp (gerçek zamanlı
        # akışta bu neredeyse time.time()'a eşittir, ama testlerde sahte/sabit
        # timestamp'lerle beslendiğinde gerçek duvar saatine göre kırpma yanlış
        # olurdu — OpenInterestDivergenceModule.update() ile aynı yaklaşım).
        self._trim(self._events[-1][0] if self._events else None)
        long_liquidated = sum(v for _, side, v in self._events if side == "SELL")
        short_liquidated = sum(v for _, side, v in self._events if side == "BUY")

        if short_liquidated >= self.threshold_usdt:
            return self._build_signal(short_liquidated, liquidated_side="SHORT", reaction_direction="LONG")
        if long_liquidated >= self.threshold_usdt:
            return self._build_signal(long_liquidated, liquidated_side="LONG", reaction_direction="SHORT")
        return ModuleSignal(False, 0, "Anormal likidasyon yok")

    def _build_signal(self, total_usdt: float, liquidated_side: str, reaction_direction: str) -> ModuleSignal:
        if self._is_still_accelerating(liquidated_side):
            return ModuleSignal(
                False,
                0,
                f"${total_usdt:,.0f} {liquidated_side} likide oldu ama şelale HÂLÂ HIZLANIYOR "
                "— tersine tepki için erken (bıçağı tutma riski, zincirleme likidasyon devam ediyor olabilir)",
            )
        return ModuleSignal(
            True,
            100,
            f"Son {self.window_seconds:.0f}sn'de ${total_usdt:,.0f} {liquidated_side} pozisyon likide oldu, "
            f"hız yavaşlıyor — tersine ({reaction_direction}) tepki ihtimali",
            direction=reaction_direction,
        )

    def _is_still_accelerating(self, liquidated_side: str) -> bool:
        """Likidasyon şelalesi hâlâ hızlanıyor mu? Pencereyi ikiye bölüp (yeni yarı / eski
        yarı) ilgili tarafın hacmini karşılaştırır. Yeni yarı eskisinden büyükse şelale
        henüz durmamış demektir — 'cascading liquidation' ortasında ters yöne (bıçağı
        tutmaya çalışarak) tetik vermek yerine önce hızın kesilmesini bekleriz.
        Karşılaştıracak eski veri yoksa (tek seferlik/ilk olay) engelleme yapmayız."""
        if not self._events:
            return False
        now = self._events[-1][0]
        midpoint = now - self.window_seconds / 2
        order_side = "SELL" if liquidated_side == "LONG" else "BUY"
        recent = sum(v for ts, side, v in self._events if side == order_side and ts >= midpoint)
        older = sum(v for ts, side, v in self._events if side == order_side and ts < midpoint)
        if older == 0:
            return False
        return recent > older


class LiquidationStreamListener:
    """`!forceOrder@arr` WebSocket akışına bağlanıp sadece izlenen sembole ait
    likidasyonları `LiquidationTracker`'a iletir. Bağlantı koparsa otomatik yeniden
    dener (backoff)."""

    def __init__(self, symbol: str, tracker: LiquidationTracker, on_event: Callable[[dict], None] | None = None) -> None:
        self.symbol = symbol.upper()
        self.tracker = tracker
        self.on_event = on_event

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                # `websockets` import'u bilerek try/except içinde: paket eksikse
                # (ModuleNotFoundError) veya başka bir başlangıç hatası olursa bu artık
                # görev sessizce ölmek yerine Olay Günlüğü'nde görünür olur ve yeniden dener.
                import websockets  # noqa: PLC0415 - opsiyonel/ağır bağımlılık, sadece kullanıldığında import edilir

                async with websockets.connect(LIQUIDATION_STREAM_URL, ping_interval=180, ping_timeout=600) as ws:
                    while not stop_event.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        except asyncio.TimeoutError:
                            continue
                        self.handle_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - WS bağlantı hatası; yeniden denenecek
                self._log_event("liquidation", f"WS bağlantı hatası, 5sn sonra yeniden denenecek: {exc}")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

    def handle_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
            order = payload.get("o", {})
            symbol = order.get("s")
            if symbol != self.symbol:
                return

            side = order.get("S")
            quantity = float(order.get("q", 0))
            price = float(order.get("ap") or order.get("p") or 0)
            self.tracker.add_liquidation(side, quantity, price)

            usdt_value = quantity * price
            self._log_event("liquidation", f"{symbol} {side} likidasyon: {quantity} @ {price} (${usdt_value:,.0f})")
        except Exception as exc:  # noqa: BLE001 - bozuk/beklenmeyen mesaj formatı
            self._log_event("liquidation", f"Mesaj ayrıştırma hatası: {exc}")

    def _log_event(self, module: str, message: str) -> None:
        if self.on_event is not None:
            self.on_event({"module": module, "message": message})
