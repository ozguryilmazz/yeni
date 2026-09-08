import asyncio

from PySide6.QtCore import QThread, Signal

from app.whale_tracker.engine import WhaleTrapEngine


class WhaleTrackerThread(QThread):
    """WhaleTrapEngine'in asyncio event loop'unu ayrı bir OS thread'inde çalıştırıp
    sonuçlarını Qt sinyalleriyle ana (GUI) thread'ine taşır. Qt'nin kendi event
    loop'u asyncio tabanlı olmadığından (qasync gibi bir köprü kütüphanesi
    kullanmadan) WebSocket dinleyicilerini/periyodik REST poll'unu doğrudan GUI
    thread'inde çalıştırmak mümkün değildir; bu yüzden kendi event loop'unu
    yöneten bir QThread kullanılır.
    """

    score_updated = Signal(object)  # TrapScoreResult
    event_logged = Signal(dict)
    error = Signal(str)

    def __init__(self, symbol: str, liquidation_threshold_usdt: float = 1_000_000) -> None:
        super().__init__()
        self.symbol = symbol
        self.liquidation_threshold_usdt = liquidation_threshold_usdt
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
        engine = WhaleTrapEngine(
            self.symbol,
            on_score=self._emit_score,
            on_event=self._emit_event,
            liquidation_threshold_usdt=self.liquidation_threshold_usdt,
        )
        await engine.run(self._stop_event)

    def _emit_score(self, result: object) -> None:
        self.score_updated.emit(result)

    def _emit_event(self, event: dict) -> None:
        self.event_logged.emit(event)

    def stop(self) -> None:
        """GUI thread'inden çağrılır; asyncio loop'una thread-safe şekilde durma
        sinyali gönderir (call_soon_threadsafe olmadan doğrudan Event.set()
        çağırmak thread-safe değildir)."""
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
