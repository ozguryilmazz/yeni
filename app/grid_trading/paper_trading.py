import asyncio
import time
from collections.abc import Callable

from app.backtest.engine import Candle
from app.binance_client import INTERVAL_MS_MAP, get_futures_kline_stats
from app.grid_trading.grid import (
    DEFAULT_FEE_RATE,
    DEFAULT_LEVERAGE,
    DEFAULT_MAINTENANCE_MARGIN_RATE,
    GridBacktestResult,
    GridEngineState,
    advance_grid_engine,
    snapshot_grid_engine,
    start_grid_engine,
)
from app.live_trading.kline_stream import KlineStreamListener

MAX_CHART_CANDLES = 500
"""Kağıt işlem süresiz çalışabildiğinden, grafik için biriktirilen mum
sayısı bellek/performans için sınırlanır -- en eski mumlar atılır."""


class GridPaperTradingEngine:
    """Grid stratejisini CANLI, gerçek zamanlı piyasa verisiyle ama SAHTE
    (kağıt) parayla çalıştırır -- gerçek emir GÖNDERMEZ, API key gerektirmez.
    app.grid_trading.grid'deki run_grid_backtest ile AYNI dolum/likidasyon
    matematiğini (bkz. start_grid_engine/advance_grid_engine/
    snapshot_grid_engine) kullanır; tek fark, mumların önceden çekilmiş bir
    listeden değil CANLI bir kline WebSocket akışından (bkz.
    app.live_trading.kline_stream.KlineStreamListener) tek tek gelmesidir —
    backtest sonuçlarının canlıda da tutarlı olup olmadığını, gerçek para
    riske atmadan doğrulamak (ileri test/forward test) içindir.

    Kurulum fiyatı olarak akıştaki İLK mum beklenmez (bu, zaman dilimine göre
    dakikalarca sürebilir) -- REST üzerinden anlık fiyat çekilip grid HEMEN
    o fiyata göre kurulur; sonra akıştan gelen HER kapanan mum motora işlenir.
    Likidasyon gerçekleşirse (bkz. app.grid_trading.grid.GridLiquidation)
    motor kendiliğinden durur -- gerçek bir grid botunda olduğu gibi elle
    yeniden başlatılması gerekir."""

    def __init__(
        self,
        symbol: str,
        interval: str,
        lower_price: float,
        upper_price: float,
        grid_count: int,
        capital_usd: float,
        on_setup: Callable[[str], None],
        on_status: Callable[[str], None],
        on_snapshot: Callable[[GridBacktestResult, list[Candle]], None],
        on_liquidated: Callable[[GridBacktestResult], None],
        on_error: Callable[[str], None],
        leverage: float = DEFAULT_LEVERAGE,
        fee_rate: float = DEFAULT_FEE_RATE,
        maintenance_margin_rate: float = DEFAULT_MAINTENANCE_MARGIN_RATE,
    ) -> None:
        self.symbol = symbol.upper()
        self.interval = interval
        self.lower_price = lower_price
        self.upper_price = upper_price
        self.grid_count = grid_count
        self.capital_usd = capital_usd
        self.leverage = leverage
        self.fee_rate = fee_rate
        self.maintenance_margin_rate = maintenance_margin_rate
        self.on_setup = on_setup
        self.on_status = on_status
        self.on_snapshot = on_snapshot
        self.on_liquidated = on_liquidated
        self.on_error = on_error

        self._state: GridEngineState | None = None
        self._candles: list[Candle] = []
        self._stop_event: asyncio.Event | None = None

    async def run(self, stop_event: asyncio.Event) -> None:
        self._stop_event = stop_event
        try:
            reference_price = get_futures_kline_stats(self.symbol, self.interval)["last_price"]
            if not reference_price:
                raise ValueError(f"{self.symbol} için anlık fiyat alınamadı (borsa boş yanıt döndürdü)")
        except Exception as exc:  # noqa: BLE001 - ağ hatası/geçersiz sembol; kullanıcıya iletilmeli
            self.on_error(f"Başlangıç fiyatı alınamadı: {exc}")
            return

        reference_time_ms = int(time.time() * 1000)
        try:
            self._state = start_grid_engine(
                reference_price, reference_time_ms, self.lower_price, self.upper_price, self.grid_count,
                self.capital_usd, self.leverage, self.fee_rate, self.maintenance_margin_rate,
            )
        except ValueError as exc:
            self.on_error(f"Grid kurulamadı: {exc}")
            return

        self.on_setup(
            f"<b>Kurulum:</b> {self.symbol} ({self.interval}) &nbsp; "
            f"<b>Başlangıç Fiyatı:</b> {reference_price:,.6f}<br>"
            f"<b>Sermaye:</b> {self.capital_usd:,.2f}$ &nbsp; <b>Kaldıraç:</b> {self.leverage:g}x &nbsp; "
            f"<b>Komisyon:</b> %{self.fee_rate * 100:g} &nbsp; "
            f"<b>Bakım Marjini:</b> %{self.maintenance_margin_rate * 100:g}<br>"
            f"<b>Grid Aralığı:</b> {self.lower_price:,.6f} - {self.upper_price:,.6f} "
            f"({self.grid_count} grid) &nbsp; <b>Grid Başına Miktar:</b> {self._state.qty_per_grid:.6f}<br>"
            f"<span style='color:#666;'>Not: başlangıç fiyatının ÜSTÜNDEKİ seviyelere kurulumda "
            f"'piyasadan alınmış' envanter seed'lenir ve bu alımın komisyonu hemen tahsil edilir — bu "
            f"yüzden fiyat henüz hiç hareket etmemiş olsa bile Toplam K/Z ilk anda hafif EKSİ görünür "
            f"(o 'piyasa alımının' komisyon maliyeti kadar); bu bir kayıp değil, normaldir.</span>"
        )
        self.on_status(f"{self.symbol} {self.interval} mum kapanışları izleniyor…")
        # İlk mum kapanışı (zaman dilimine göre dakikalarca) beklenmeden grafik/grid
        # çizgileri hemen görünsün diye, henüz gerçek mum yokken başlangıç fiyatında
        # düz (open=high=low=close) iki 'yer tutucu' mum kullanılır -- bunlar sadece
        # çizim ekseni için bir zaman aralığı sağlar, self._candles'a EKLENMEZ (ilk
        # gerçek mum geldiğinde grafik sahte veri karışmadan gerçek veriye geçer)."""
        interval_ms = INTERVAL_MS_MAP[self.interval]
        placeholder_candles = [
            Candle(
                open_time_ms=reference_time_ms,
                open=reference_price,
                high=reference_price,
                low=reference_price,
                close=reference_price,
            ),
            Candle(
                open_time_ms=reference_time_ms + interval_ms,
                open=reference_price,
                high=reference_price,
                low=reference_price,
                close=reference_price,
            ),
        ]
        self.on_snapshot(snapshot_grid_engine(self._state, reference_price, reference_time_ms), placeholder_candles)

        listener = KlineStreamListener(self.symbol, self.interval, on_error=self.on_status)
        await listener.run(stop_event, self._on_candle_closed)

    def _on_candle_closed(self, candle: Candle) -> None:
        self._candles.append(candle)
        if len(self._candles) > MAX_CHART_CANDLES:
            self._candles.pop(0)

        liquidation = advance_grid_engine(self._state, candle)
        result = snapshot_grid_engine(self._state, candle.close, candle.open_time_ms)
        self.on_snapshot(result, list(self._candles))

        if liquidation:
            self.on_status(
                f"LİKİDE OLDU: {liquidation.liquidation_price:,.6f} fiyatında pozisyon zorla kapatıldı — "
                f"kağıt işlem durduruluyor (bot gerçek hayatta olduğu gibi elle yeniden başlatılmalı)."
            )
            self.on_liquidated(result)
            if self._stop_event is not None:
                self._stop_event.set()
