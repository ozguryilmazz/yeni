import asyncio

from PySide6.QtCore import QThread, Signal

from app.grid_trading.grid import DEFAULT_FEE_RATE, DEFAULT_LEVERAGE, DEFAULT_MAINTENANCE_MARGIN_RATE
from app.grid_trading.paper_trading import GridPaperTradingEngine


class GridPaperTradingThread(QThread):
    """GridPaperTradingEngine'in asyncio event loop'unu ayrı bir OS
    thread'inde çalıştırıp sonuçlarını Qt sinyalleriyle ana (GUI) thread'ine
    taşır — app.live_trading.qt_bridge.LiveTradingThread ile aynı desen."""

    setup_info = Signal(str)
    status = Signal(str)
    snapshot_updated = Signal(object, list)  # GridBacktestResult, list[Candle]
    liquidated = Signal(object)  # GridBacktestResult
    error = Signal(str)

    def __init__(
        self,
        symbol: str,
        interval: str,
        lower_price: float,
        upper_price: float,
        grid_count: int,
        capital_usd: float,
        leverage: float = DEFAULT_LEVERAGE,
        fee_rate: float = DEFAULT_FEE_RATE,
        maintenance_margin_rate: float = DEFAULT_MAINTENANCE_MARGIN_RATE,
    ) -> None:
        super().__init__()
        self._symbol = symbol
        self._interval = interval
        self._lower_price = lower_price
        self._upper_price = upper_price
        self._grid_count = grid_count
        self._capital_usd = capital_usd
        self._leverage = leverage
        self._fee_rate = fee_rate
        self._maintenance_margin_rate = maintenance_margin_rate
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None

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
        engine = GridPaperTradingEngine(
            symbol=self._symbol,
            interval=self._interval,
            lower_price=self._lower_price,
            upper_price=self._upper_price,
            grid_count=self._grid_count,
            capital_usd=self._capital_usd,
            leverage=self._leverage,
            fee_rate=self._fee_rate,
            maintenance_margin_rate=self._maintenance_margin_rate,
            on_setup=self._emit_setup_info,
            on_status=self._emit_status,
            on_snapshot=self._emit_snapshot,
            on_liquidated=self._emit_liquidated,
            on_error=self._emit_error,
        )
        await engine.run(self._stop_event)

    def _emit_setup_info(self, message: str) -> None:
        self.setup_info.emit(message)

    def _emit_status(self, message: str) -> None:
        self.status.emit(message)

    def _emit_snapshot(self, result, candles) -> None:
        self.snapshot_updated.emit(result, candles)

    def _emit_liquidated(self, result) -> None:
        self.liquidated.emit(result)

    def _emit_error(self, message: str) -> None:
        self.error.emit(message)

    def stop(self) -> None:
        """GUI thread'inden çağrılır; asyncio loop'una thread-safe şekilde
        durma sinyali gönderir. Gerçek emir hiç gönderilmediğinden
        iptal edilecek/kapatılacak bir şey yoktur — sadece akışı dinlemeyi
        bırakır."""
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
