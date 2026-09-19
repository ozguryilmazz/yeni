import asyncio

from PySide6.QtCore import QThread, Signal

from app.live_trading.engine import LiveTradingEngine, RiskParams
from app.strategies.base import Strategy


class LiveTradingThread(QThread):
    """LiveTradingEngine'in asyncio event loop'unu ayrı bir OS thread'inde
    çalıştırıp sonuçlarını Qt sinyalleriyle ana (GUI) thread'ine taşır —
    app.whale_tracker.qt_bridge.WhaleTrackerThread ile aynı desen."""

    status = Signal(str)
    signal_detected = Signal(str, float)
    confirmation_needed = Signal(str, float, float, float)  # side, price, stop_loss, take_profit
    order_placed = Signal(dict)
    position_closed = Signal(str)  # exit_reason: "TP" | "SL" | "UNKNOWN"
    error = Signal(str)

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        symbol: str,
        interval: str,
        strategy: Strategy,
        risk: RiskParams,
        mode: str,
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self._api_secret = api_secret
        self._symbol = symbol
        self._interval = interval
        self._strategy = strategy
        self._risk = risk
        self._mode = mode
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._engine: LiveTradingEngine | None = None

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:  # noqa: BLE001 - UI'ya taşınacak, tipi önemli değil
            self.error.emit(str(exc))
        finally:
            self._loop.close()
            self._loop = None

    async def _main(self) -> None:
        self._stop_event = asyncio.Event()
        self._engine = LiveTradingEngine(
            api_key=self._api_key,
            api_secret=self._api_secret,
            symbol=self._symbol,
            interval=self._interval,
            strategy=self._strategy,
            risk=self._risk,
            mode=self._mode,
            on_status=self._emit_status,
            on_signal=self._emit_signal,
            on_confirmation_needed=self._emit_confirmation_needed,
            on_order_placed=self._emit_order_placed,
            on_position_closed=self._emit_position_closed,
            on_error=self._emit_error,
        )
        await self._engine.run(self._stop_event)

    def _emit_status(self, message: str) -> None:
        self.status.emit(message)

    def _emit_signal(self, side: str, price: float) -> None:
        self.signal_detected.emit(side, price)

    def _emit_confirmation_needed(self, side: str, price: float, stop_loss: float, take_profit: float) -> None:
        self.confirmation_needed.emit(side, price, stop_loss, take_profit)

    def _emit_order_placed(self, trade: dict) -> None:
        self.order_placed.emit(trade)

    def _emit_position_closed(self, exit_reason: str) -> None:
        self.position_closed.emit(exit_reason)

    def _emit_error(self, message: str) -> None:
        self.error.emit(message)

    def stop(self) -> None:
        """GUI thread'inden çağrılır; asyncio loop'una thread-safe şekilde durma
        sinyali gönderir. Borsada zaten açık olan SL/TP emirlerini İPTAL ETMEZ —
        bot sadece yeni sinyal aramayı durdurur, mevcut pozisyon (varsa) borsa
        tarafındaki koruma emirleriyle korunmaya devam eder."""
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    def confirm_pending_signal(self) -> None:
        """GUI thread'inden çağrılır (yalnızca mode='confirm')."""
        if self._loop is not None and self._engine is not None:
            self._loop.call_soon_threadsafe(self._engine.confirm_and_execute)

    def reject_pending_signal(self) -> None:
        """GUI thread'inden çağrılır (yalnızca mode='confirm')."""
        if self._loop is not None and self._engine is not None:
            self._loop.call_soon_threadsafe(self._engine.reject_pending_signal)
