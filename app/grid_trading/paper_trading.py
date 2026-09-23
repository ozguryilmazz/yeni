import asyncio
import time
from collections.abc import Callable

from app.backtest.engine import Candle
from app.binance_client import INTERVAL_MS_MAP, get_futures_kline_stats, get_futures_recent_klines
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

MAX_CHART_CANDLES = 500
"""Kağıt işlem süresiz çalışabildiğinden, grafik için biriktirilen mum
sayısı bellek/performans için sınırlanır -- en eski mumlar atılır."""

POLL_INTERVAL_SECONDS = 5.0
"""Mum verisi WebSocket akışı YERİNE REST polling ile çekilir: bazı ağ
ortamlarında (güvenlik duvarı/proxy) WebSocket bağlantısı el sıkışmayı
tamamlayıp sonrasında veriyi SESSİZCE düşürebiliyor (bkz.
app.live_trading.kline_stream.STALE_CONNECTION_SECONDS) ve bu, uygulamanın
kontrolü dışında bir ağ sorunu; REST istekleri ise bu ortamda güvenilir
çalışıyor. Grid motoru zaten sadece KAPANAN mum bilgisine ihtiyaç duyduğundan
(tick verisi gerekmez), her POLL_INTERVAL_SECONDS saniyede bir en son mumlar
çekilip yeni kapanan(lar) tespit edilir -- işlevsel olarak WS akışıyla eşdeğer."""


class GridPaperTradingEngine:
    """Grid stratejisini CANLI, gerçek zamanlı piyasa verisiyle ama SAHTE
    (kağıt) parayla çalıştırır -- gerçek emir GÖNDERMEZ, API key gerektirmez.
    app.grid_trading.grid'deki run_grid_backtest ile AYNI dolum/likidasyon
    matematiğini (bkz. start_grid_engine/advance_grid_engine/
    snapshot_grid_engine) kullanır; tek fark, mumların önceden çekilmiş bir
    listeden değil CANLI olarak REST polling ile (bkz. POLL_INTERVAL_SECONDS)
    tek tek gelmesidir — backtest sonuçlarının canlıda da tutarlı olup
    olmadığını, gerçek para riske atmadan doğrulamak (ileri test/forward
    test) içindir.

    Kurulum fiyatı olarak İLK mumun kapanması beklenmez (bu, zaman dilimine
    göre dakikalarca sürebilir) -- REST üzerinden anlık fiyat çekilip grid
    HEMEN o fiyata göre kurulur; sonra REST polling ile (bkz.
    POLL_INTERVAL_SECONDS) tespit edilen HER yeni kapanan mum motora işlenir.
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
        self._last_closed_open_time_ms: int | None = None

    async def run(self, stop_event: asyncio.Event) -> None:
        self._stop_event = stop_event
        try:
            reference_price = get_futures_kline_stats(self.symbol, self.interval)["last_price"]
            if not reference_price:
                raise ValueError(f"{self.symbol} için anlık fiyat alınamadı (borsa boş yanıt döndürdü)")
        except Exception as exc:  # noqa: BLE001 - ağ hatası/geçersiz sembol; kullanıcıya iletilmeli
            self.on_error(f"Başlangıç fiyatı alınamadı: {exc}")
            return

        # Binance kline'ları için fills/trades HER ZAMAN candle.open_time_ms ile
        # damgalanır (bkz. app.grid_trading.grid) -- bir mum, GERÇEKTE kapandığı
        # andan (open_time + interval kadar SONRA) değil, kendi AÇILIŞ anından
        # etiketlenir. Kurulumda seed'lenen envanterin 'alış zamanı' ise ham
        # time.time() (an itibarıyla 'şimdi') kullanılırsa, bu iki farklı zaman
        # tabanı en fazla bir mum aralığı kadar birbirinden kayar -- setup'tan
        # SONRA gerçekleşen bir satış bile, tetikleyen mumun açılışı setup
        # anından ÖNCEYSE ekranda 'satış, alıştan önce' gibi görünür (yanıltıcı
        # ama YANLIŞ değil). Bunu önlemek için referans zamanı da aynı
        # kapanmamış mumun açılışına -- güncel dilim sınırına -- yuvarlanır.
        interval_ms = INTERVAL_MS_MAP[self.interval]
        reference_time_ms = (int(time.time() * 1000) // interval_ms) * interval_ms
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

        self._prime_last_closed_candle()
        await self._poll_loop(stop_event)

    def _prime_last_closed_candle(self) -> None:
        """REST polling, WebSocket akışından FARKLI olarak sadece 'yeni' değil
        GEÇMİŞ (paper trading başlamadan ÖNCE zaten kapanmış) mumları da döner.
        _poll_loop ilk turunda self._last_closed_open_time_ms hâlâ None ise, o
        turda dönen TÜM kapanmış mumları 'yeni kapandı' sayıp motora işler --
        bu da kağıt işlem daha canlıda hiçbir fiyat görmeden, geçmiş fiyat
        hareketiyle anında ('zamanda geriye dönük') dolumlar oluşturur. Bunu
        önlemek için burada watermark'ı, HİÇBİR mumu motora işlemeden, şu ana
        kadar zaten kapanmış son muma göre önceden ayarlıyoruz -- motor, ilk
        gerçek kapanışla tıpkı WebSocket akışındaki gibi başlar."""
        try:
            raw_klines = get_futures_recent_klines(self.symbol, self.interval, limit=2)
            closed = raw_klines[:-1]  # bkz. _poll_loop -- son eleman her zaman kapanmamış sayılır
            if closed:
                self._last_closed_open_time_ms = int(closed[-1][0])
        except Exception as exc:  # noqa: BLE001 - ağ hatası; ilk poll turu kendi hatasını raporlayıp yine de devam eder
            self.on_status(f"Başlangıç mumu belirlenemedi, ilk pollda tekrar denenecek: {exc}")

    async def _poll_loop(self, stop_event: asyncio.Event) -> None:
        """WebSocket akışı yerine REST polling: her POLL_INTERVAL_SECONDS
        saniyede bir en son mumlar çekilir, kapanmış olanlardan daha önce
        işlenmemiş olanlar (open_time_ms ile takip edilir) motora işlenir.
        Birden fazla mum kaçırılmışsa (ör. geçici ağ hatası) hepsi sırayla
        işlenir -- sadece en sonuncusu değil."""
        while not stop_event.is_set():
            try:
                raw_klines = get_futures_recent_klines(self.symbol, self.interval, limit=5)
            except Exception as exc:  # noqa: BLE001 - ağ hatası; bir sonraki denemede düzelebilir
                self.on_status(f"Mum verisi çekilemedi, {POLL_INTERVAL_SECONDS:.0f}sn sonra tekrar denenecek: {exc}")
                raw_klines = []

            # Binance, startTime/endTime VERİLMEDEN çağrıldığında SON elemanı her
            # zaman henüz kapanmamış (o an oluşan) mum olarak döner (bkz.
            # get_futures_recent_klines docstring'i) -- kapanma kontrolü için
            # yerel saate (time.time()) ihtiyaç yok. Bu, makinenin saati Binance
            # sunucu saatinden kaysa bile (ör. NTP senkronu bozuksa) doğru çalışır;
            # eski kod close_time_ms<=now_ms ile yerel saate kıyaslıyordu.
            candle_closed = False
            for k in raw_klines[:-1]:
                open_time_ms = int(k[0])
                if self._last_closed_open_time_ms is not None and open_time_ms <= self._last_closed_open_time_ms:
                    continue  # daha önce işlendi
                candle = Candle(
                    open_time_ms=open_time_ms,
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                )
                self._last_closed_open_time_ms = open_time_ms
                self._on_candle_closed(candle)
                candle_closed = True

            # Yüksek zaman dilimlerinde (1h/4h/1d) ilk mum kapanana kadar uzunca
            # bir süre hiçbir güncelleme olmaması kullanıcıya botun takıldığı
            # izlenimini verebiliyordu -- botun çalıştığını ve sadece sıradaki
            # kapanışı beklediğini göstermek için durum mesajına kalan süre
            # eklenir. Likidasyon/durdurma nedeniyle döngüden zaten çıkılacaksa
            # (stop_event set edildiyse) o mesajın üzerine yazılmaz.
            if raw_klines and not stop_event.is_set():
                self._update_waiting_status(raw_klines[-1])
                # Bu turda bir mum ZATEN kapandıysa _on_candle_closed kendi
                # snapshot'ını yayınladı -- burada TEKRAR yayınlamaya gerek yok.
                # Kapanmadıysa (ki poll aralığı mum aralığından çok daha kısa
                # olduğundan turların BÜYÜK çoğunluğu bu durumdadır), güncel
                # fiyatı/açık pozisyonların anlık K/Z'ını yine de tazelemek
                # için o an oluşan mumun SON fiyatıyla bir snapshot yayınlanır
                # (bkz. kullanıcı talebi: fiyat/K/Z ~5 saniyede bir güncellensin).
                if not candle_closed:
                    self._report_live_price(raw_klines[-1])

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass

    def _update_waiting_status(self, forming_kline: list) -> None:
        close_time_ms = int(forming_kline[6])
        remaining_ms = close_time_ms - int(time.time() * 1000)
        self.on_status(
            f"{self.symbol} {self.interval} mum kapanışları izleniyor… "
            f"(sıradaki kapanış: ~{_format_remaining_time(remaining_ms)})"
        )

    def _report_live_price(self, forming_kline: list) -> None:
        """Yeni bir mum kapanmasa bile, o an oluşmakta olan mumun SON fiyatıyla
        bir snapshot yayınlar -- fiyat göstergesi ve açık pozisyonların anlık
        (mark-to-market) K/Z'ı, sadece mum kapanışlarında değil her poll
        turunda (~POLL_INTERVAL_SECONDS'ta bir) tazelensin diye."""
        live_price = float(forming_kline[4])
        live_time_ms = int(forming_kline[0])
        self.on_snapshot(snapshot_grid_engine(self._state, live_price, live_time_ms), list(self._candles))

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


def _format_remaining_time(remaining_ms: int) -> str:
    """Kalan süreyi en büyük ANLAMLI birimden başlayarak ('Xsa Ydk' / 'Xdk Ysn' /
    'Xsn') okunur bir metne çevirir -- ör. '4h' zaman diliminde saniye
    hassasiyeti gereksiz/kalabalık olurdu (bkz. _update_waiting_status).
    Negatif değer (ör. yerel saat Binance sunucu saatinden geride kaldıysa)
    '0sn' olarak gösterilir -- sıradaki pollda zaten yeni kapanmış mum
    yakalanacaktır."""
    remaining_s = max(0, remaining_ms // 1000)
    hours, rem_s = divmod(remaining_s, 3600)
    minutes, seconds = divmod(rem_s, 60)
    if hours:
        return f"{hours}sa {minutes}dk"
    if minutes:
        return f"{minutes}dk {seconds}sn"
    return f"{seconds}sn"
