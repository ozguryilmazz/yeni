from dataclasses import dataclass

from app.backtest.engine import Candle
from app.position_sizing import TAKER_FEE_RATE

DEFAULT_GRID_COUNT = 30
"""Kullanıcı notlarındaki varsayılan: alt/üst sınır arasında 30 eşit parça.
Backtest/canlı öncesi değiştirilebilir."""

DEFAULT_LEVERAGE = 1.0
DEFAULT_FEE_RATE = TAKER_FEE_RATE
"""Varsayılan komisyon oranı olarak taker (%0.05, maker'dan yüksek) kullanılır:
30 seviyeli sık dolumlu bir grid'de HER emrin maker (limit, kuyruğa girip
karşılanan) olarak dolacağını varsaymak iyimserdir -- kısmi dolum/kuyruk
gecikmesi gibi nedenlerle bazı dolumlar fiilen taker olabilir. Daha
muhafazakâr/gerçekçi bir tahmin için tek tip taker oranı kullanılır."""

DEFAULT_MAINTENANCE_MARGIN_RATE = 0.005
"""Binance'in gerçek bakım marjin oranı sembole ve pozisyon büyüklüğü
(notional) katmanına göre değişir (major coinlerde genelde ~%0.4-0.5,
altcoinlerde ilk katmanda daha yüksek olabilir); bu sabit tüm semboller
için makul bir yaklaşıklıktır, kesin değil -- gerekirse backtest'te
elle ayarlanabilir."""


def build_grid_levels(lower_price: float, upper_price: float, grid_count: int) -> list[float]:
    """`lower_price`/`upper_price` arasında `grid_count` eşit PARÇALI (aritmetik,
    eşit fiyat aralıklı) `grid_count + 1` seviye döner."""
    if lower_price >= upper_price:
        raise ValueError("lower_price, upper_price'dan küçük olmalı")
    if grid_count < 1:
        raise ValueError("grid_count en az 1 olmalı")

    step = (upper_price - lower_price) / grid_count
    return [lower_price + step * i for i in range(grid_count + 1)]


@dataclass
class GridFill:
    """Tek bir emrin dolumu (ham denetim kaydı — bkz. GridTrade for tamamlanmış
    alım-satım çiftleri)."""

    side: str  # "BUY" | "SELL"
    time_ms: int
    price: float
    quantity: float
    fee_rate: float


@dataclass
class GridTrade:
    """Bir alt seviyeden alıp bir üst seviyeden satarak tamamlanan tek bir grid
    hücresi kâr/zararı (bkz. run_grid_backtest'teki 'yeniden kurulum' mantığı)."""

    buy_price: float
    sell_price: float
    quantity: float
    buy_time_ms: int
    sell_time_ms: int
    gross_pnl_usd: float
    fees_usd: float
    net_pnl_usd: float


@dataclass
class GridLiquidation:
    """Kaldıraçlı toplam pozisyonun (o ana kadar biriken TÜM açık envanterin,
    ağırlıklı ortalama giriş fiyatıyla) izole marjini bakım marjinine değdiğinde
    zorla kapatılması. Gerçekleştiğinde grid'in TÜM açık emirleri iptal edilir
    (bkz. run_grid_backtest) -- bot durur, elle yeniden başlatılması gerekir."""

    time_ms: int
    liquidation_price: float
    position_qty: float
    avg_entry_price: float
    margin_lost_usd: float
    """Likidasyon anında izole marjin cüzdanında kalan (ve kaybedilen) bakiye
    -- bkz. _compute_available_margin. Bu SIFIRA yakındır (bakım marjini
    eşiğine değdiği an tetiklenir); toplam sonuç raporlanırken (bkz.
    GridBacktestResult.total_pnl_usd) daha basit ve muhafazakâr bir kural
    kullanılır: likidasyon olursa başlangıç sermayesinin TAMAMI kaybedilmiş
    sayılır (o ana kadar gerçekleşen kârlar da AYNI izole cüzdanda olduğundan
    kullanıcı onları ayrıca çekmediyse onlar da likidasyonla gider)."""


@dataclass
class GridBacktestResult:
    grid_levels: list[float]
    trades: list[GridTrade]
    fills: list[GridFill]
    realized_pnl_usd: float
    """Likidasyon ÖNCESİNDE tamamlanmış (alım+satım ikilisi kapanmış)
    hücrelerin toplam net K/Z'ı -- bilgi amaçlı; likidasyon olduysa bu
    kârlar da izole marjinle birlikte kaybedilmiştir (bkz. total_pnl_usd)."""
    unrealized_pnl_usd: float
    """Backtest sonunda hâlâ elde tutulan (satılmamış) envanterin, o envanteri
    almak için ödenen komisyon dahil maliyete göre mark-to-market K/Z'ı.
    Likidasyon olduysa 0 (pozisyon zorla kapatılmıştır)."""
    total_pnl_usd: float
    """Likidasyon olmadıysa realized_pnl_usd + unrealized_pnl_usd. Likidasyon
    olduysa -capital_usd (izole marjinin tamamı kaybedilmiş sayılır)."""
    fees_usd: float
    """TÜM dolumlarda (açık pozisyonlar ve likidasyon ÖNCESİ dahil) ödenen
    toplam komisyon."""
    capital_usd: float
    leverage: float
    fee_rate: float
    maintenance_margin_rate: float
    qty_per_grid: float
    final_inventory_qty: float
    final_inventory_value_usd: float
    start_price: float
    end_price: float
    min_price_seen: float
    max_price_seen: float
    breached_lower: bool
    """Fiyat, backtest sırasında en az bir kez alt sınırın (grid_levels[0]) altına indi mi."""
    breached_upper: bool
    """Fiyat, backtest sırasında en az bir kez üst sınırın (grid_levels[-1]) üstüne çıktı mı."""
    open_buy_levels: list[float]
    open_sell_levels: list[float]
    liquidated: bool
    liquidation: GridLiquidation | None


def run_grid_backtest(
    candles: list[Candle],
    lower_price: float,
    upper_price: float,
    grid_count: int,
    capital_usd: float,
    leverage: float = DEFAULT_LEVERAGE,
    fee_rate: float = DEFAULT_FEE_RATE,
    maintenance_margin_rate: float = DEFAULT_MAINTENANCE_MARGIN_RATE,
) -> GridBacktestResult:
    """Verilen mum dizisi üzerinde bir arithmetic grid'in AL/SAT dolumlarını
    (ve kaldıraçlıysa likidasyon riskini) simüle eder.

    Kurulum: `capital_usd × leverage` (margin × kaldıraç = nominal pozisyon
    büyüklüğü, bkz. app.position_sizing.compute_position_sizing'deki aynı
    kural) `grid_count`'a eşit bölünüp ilk mumun açılışına göre SABİT bir
    taban varlık miktarına (`qty_per_grid`) çevrilir. `leverage=1`
    (varsayılan) kaldıraçsız/spot-eşdeğeri davranıştır.

    Başlangıç fiyatının ALTINDAKİ her seviyede bekleyen bir AL (limit) emri
    vardır. ÜSTÜNDEKİ seviyeler için ise gerçek grid botlarının (ör. Binance
    Nötr Grid) yaptığı gibi kurulumda PİYASADAN o seviyeler kadar envanter
    alınmış kabul edilip oraya hemen bir SAT emri konur (bkz. modül
    docstring'inde detaylı gerekçe). Bir AL dolunca bir üst seviyeye SAT
    emri konur; o SAT da dolunca kâr/zarar gerçekleşir ve BİR ALT seviyeye
    AL emri yeniden kurulur.

    Komisyon: TÜM dolumlarda (kurulum seed'i dahil) TEK bir `fee_rate`
    uygulanır; varsayılan taker oranıdır (bkz. DEFAULT_FEE_RATE).

    LİKİDASYON (kaldıraç > 1 iken önemli): o anki TÜM açık envanter (henüz
    satılmamış tüm AL pozisyonları, kurulum seed'i dahil), tek bir izole
    marjin pozisyonu gibi TOPLU olarak izlenir -- ağırlıklı ortalama giriş
    fiyatı ve toplam miktar üzerinden bir likidasyon fiyatı hesaplanır
    (bkz. _compute_liquidation_price). İzole marjin cüzdanı `capital_usd`
    ile başlar; ödenen her komisyon bu cüzdanı azaltır, tamamlanan her grid
    hücresinin brüt kârı bu cüzdanı büyütür (bkz. _compute_available_margin)
    -- yani backtest boyunca gerçekleşen kârlar likidasyon riskini gerçekçi
    şekilde AZALTIR. Fiyat bu likidasyon seviyesine değerse (sadece AŞAĞI
    yönde risklidir -- grid hep LONG envanter biriktirir) TÜM açık envanter
    o fiyattan zorla kapatılır, TÜM bekleyen emirler iptal edilir ve
    backtest orada durur (bkz. GridBacktestResult.liquidated/liquidation) --
    gerçek hayatta olduğu gibi bot orada durur, elle yeniden başlatılması
    gerekir. `leverage=1` ile likidasyon pratik olarak imkânsıza yakındır
    (bkz. modülün UYARI notu: bu basitleştirilmiş bir yaklaşıklıktır, gerçek
    Binance likidasyon motoru daha karmaşıktır).

    Fiyat aralığın dışına çıkarsa (breached_lower/breached_upper) o yöndeki
    emirler tükenir ve motor kendiliğinden yeni emir açmaz — kalan envanter
    sadece mark-to-market izlenir; bu, likidasyondan AYRI bir durumdur (grid
    sınırı ile likidasyon fiyatı farklı kavramlardır, likidasyon genelde
    grid'in çok altında olur).

    Mum içi gerçek fiyat yolu bilinmediğinden her mum, açılıştan mumun
    KAPANIŞ YÖNÜNE göre önce ZIT uca sonra kapanış yönündeki uca doğru iki
    parçada taranır (bkz. _process_candle) — böylece [low, high] aralığının
    tamamı (sadece net yönü değil) dolum kontrolüne dahil olur."""
    if not candles:
        raise ValueError("Backtest için en az bir mum gerekli")
    if capital_usd <= 0:
        raise ValueError("capital_usd pozitif olmalı")
    if leverage <= 0:
        raise ValueError("leverage pozitif olmalı")

    levels = build_grid_levels(lower_price, upper_price, grid_count)
    start_price = candles[0].open
    start_time_ms = candles[0].open_time_ms
    qty_per_grid = (capital_usd * leverage / grid_count) / start_price

    pending_buys: set[int] = set()
    pending_sells: dict[int, tuple[float, int]] = {}  # sell_level_index -> (buy_price, buy_time_ms)
    fills: list[GridFill] = []
    trades: list[GridTrade] = []

    for i, level in enumerate(levels):
        if level < start_price:
            pending_buys.add(i)
        elif level > start_price:
            pending_sells[i] = (start_price, start_time_ms)
            fills.append(
                GridFill(side="BUY", time_ms=start_time_ms, price=start_price, quantity=qty_per_grid, fee_rate=fee_rate)
            )

    min_price_seen = start_price
    max_price_seen = start_price
    last_candle = candles[0]
    liquidation: GridLiquidation | None = None

    for candle in candles:
        last_candle = candle
        min_price_seen = min(min_price_seen, candle.low)
        max_price_seen = max(max_price_seen, candle.high)
        liquidation = _process_candle(
            candle, levels, pending_buys, pending_sells, qty_per_grid, fee_rate,
            trades, fills, capital_usd, maintenance_margin_rate,
        )
        if liquidation:
            break

    fees_usd = sum(f.price * f.quantity * f.fee_rate for f in fills)
    realized_pnl_usd = sum(t.net_pnl_usd for t in trades)

    final_inventory_qty = len(pending_sells) * qty_per_grid
    cost_basis_usd = sum(buy_price * qty_per_grid * (1 + fee_rate) for buy_price, _ in pending_sells.values())
    end_price = liquidation.liquidation_price if liquidation else last_candle.close
    final_inventory_value_usd = final_inventory_qty * end_price
    unrealized_pnl_usd = final_inventory_value_usd - cost_basis_usd

    total_pnl_usd = -capital_usd if liquidation else realized_pnl_usd + unrealized_pnl_usd

    return GridBacktestResult(
        grid_levels=levels,
        trades=trades,
        fills=fills,
        realized_pnl_usd=realized_pnl_usd,
        unrealized_pnl_usd=unrealized_pnl_usd,
        total_pnl_usd=total_pnl_usd,
        fees_usd=fees_usd,
        capital_usd=capital_usd,
        leverage=leverage,
        fee_rate=fee_rate,
        maintenance_margin_rate=maintenance_margin_rate,
        qty_per_grid=qty_per_grid,
        final_inventory_qty=final_inventory_qty,
        final_inventory_value_usd=final_inventory_value_usd,
        start_price=start_price,
        end_price=end_price,
        min_price_seen=min_price_seen,
        max_price_seen=max_price_seen,
        breached_lower=min_price_seen <= levels[0],
        breached_upper=max_price_seen >= levels[-1],
        open_buy_levels=sorted(levels[i] for i in pending_buys),
        open_sell_levels=sorted(levels[i] for i in pending_sells),
        liquidated=liquidation is not None,
        liquidation=liquidation,
    )


def _compute_available_margin(capital_usd: float, fills: list[GridFill], trades: list[GridTrade]) -> float:
    """İzole marjin cüzdanının o anki bakiyesi: `capital_usd` ile başlar, o
    ana kadar ödenen TÜM komisyonlar (açık pozisyonlar dahil) düşer,
    tamamlanmış her grid hücresinin BRÜT kârı (komisyon zaten ayrı
    düşüldüğünden net değil brüt) eklenir."""
    fees_paid = sum(f.price * f.quantity * f.fee_rate for f in fills)
    realized_gross = sum(t.gross_pnl_usd for t in trades)
    return capital_usd - fees_paid + realized_gross


def _compute_liquidation_price(
    pending_sells: dict[int, tuple[float, int]], qty_per_grid: float, available_margin: float, maintenance_margin_rate: float
) -> float | None:
    """O anki TÜM açık envanteri (pending_sells'teki her giriş bir henüz
    satılmamış AL pozisyonudur) TEK bir izole marjin pozisyonu gibi ele alıp
    ağırlıklı ortalama giriş fiyatından likidasyon fiyatını hesaplar. Açık
    pozisyon yoksa (pending_sells boşsa) likidasyon riski de yoktur -> None."""
    if not pending_sells:
        return None
    position_qty = len(pending_sells) * qty_per_grid
    notional = sum(buy_price for buy_price, _ in pending_sells.values()) * qty_per_grid
    avg_entry_price = notional / position_qty
    return avg_entry_price * (1 + maintenance_margin_rate) - available_margin / position_qty


def _process_candle(
    candle: Candle,
    levels: list[float],
    pending_buys: set[int],
    pending_sells: dict[int, tuple[float, int]],
    qty_per_grid: float,
    fee_rate: float,
    trades: list[GridTrade],
    fills: list[GridFill],
    capital_usd: float,
    maintenance_margin_rate: float,
) -> GridLiquidation | None:
    """Bu mumda tetiklenen TÜM grid emirlerini işler; likidasyon tetiklenirse
    (bkz. _sweep) onu döner ve kalan tarama durur. Mum içi yol varsayımı:
    kapanış açılıştan yüksekse önce açılıştan düşüğe (olası bir düşüş),
    sonra düşükten yükseğe (ralli); kapanış düşükse tam tersi. Bu, [low,
    high] aralığının TAMAMININ (sadece net kapanış yönünün değil) dolum
    kontrolüne girmesini sağlar."""
    common_args = (
        candle, levels, pending_buys, pending_sells, qty_per_grid, fee_rate, trades, fills, capital_usd, maintenance_margin_rate,
    )
    if candle.close >= candle.open:
        legs = [(candle.open, candle.low, False), (candle.low, candle.high, True)]
    else:
        legs = [(candle.open, candle.high, True), (candle.high, candle.low, False)]

    for from_price, to_price, ascending in legs:
        liquidation = _sweep(*common_args, from_price, to_price, ascending)
        if liquidation:
            return liquidation
    return None


def _sweep(
    candle: Candle,
    levels: list[float],
    pending_buys: set[int],
    pending_sells: dict[int, tuple[float, int]],
    qty_per_grid: float,
    fee_rate: float,
    trades: list[GridTrade],
    fills: list[GridFill],
    capital_usd: float,
    maintenance_margin_rate: float,
    from_price: float,
    to_price: float,
    ascending: bool,
) -> GridLiquidation | None:
    """`from_price`'tan `to_price`'a TEK YÖNLÜ (monotonik) bir fiyat hareketi
    boyunca tetiklenen emirleri, en yakından en uzağa sırayla işler — bir
    dolumun doğurduğu yeni emir bu sweep'in GERİSİNDE kalıyorsa (ör. bir SAT
    dolumunun yeniden kurduğu AL, aşağıda kalır) bu sweep içinde tekrar
    işlenmez, bir sonraki sweep/mumu bekler. SADECE düşüş (ascending=False)
    yönünde, her adımda o anki (o ana kadarki dolumlara göre güncel) izole
    marjin likidasyon fiyatı da bir sonraki grid dolumuyla birlikte
    değerlendirilir -- likidasyon fiyatı bir sonraki grid seviyesinden ÖNCE
    (fiyata daha yakın) ise likidasyon önce gerçekleşir, TÜM açık envanter o
    fiyattan kapatılır ve TÜM bekleyen emirler iptal edilir."""
    lo, hi = (from_price, to_price) if ascending else (to_price, from_price)
    cursor = from_price

    while True:
        if ascending:
            candidates = [i for i in pending_buys if cursor <= levels[i] <= hi]
            candidates += [i for i in pending_sells if cursor <= levels[i] <= hi]
        else:
            candidates = [i for i in pending_buys if lo <= levels[i] <= cursor]
            candidates += [i for i in pending_sells if lo <= levels[i] <= cursor]

        next_index = (min if ascending else max)(candidates, key=lambda i: levels[i]) if candidates else None
        next_grid_price = levels[next_index] if next_index is not None else None

        if not ascending:
            available_margin = _compute_available_margin(capital_usd, fills, trades)
            liq_price = _compute_liquidation_price(pending_sells, qty_per_grid, available_margin, maintenance_margin_rate)
            if (
                liq_price is not None
                and lo <= liq_price <= cursor
                and (next_grid_price is None or liq_price >= next_grid_price)
            ):
                position_qty = len(pending_sells) * qty_per_grid
                notional = sum(buy_price for buy_price, _ in pending_sells.values()) * qty_per_grid
                liquidation = GridLiquidation(
                    time_ms=candle.open_time_ms,
                    liquidation_price=liq_price,
                    position_qty=position_qty,
                    avg_entry_price=notional / position_qty,
                    margin_lost_usd=available_margin,
                )
                pending_buys.clear()
                pending_sells.clear()
                return liquidation

        if next_index is None:
            break

        cursor = next_grid_price
        if next_index in pending_buys:
            _fill_buy(next_index, candle, levels, pending_buys, pending_sells, qty_per_grid, fee_rate, fills)
        else:
            _fill_sell(next_index, candle, levels, pending_buys, pending_sells, qty_per_grid, fee_rate, trades, fills)
    return None


def _fill_buy(
    index: int,
    candle: Candle,
    levels: list[float],
    pending_buys: set[int],
    pending_sells: dict[int, tuple[float, int]],
    qty_per_grid: float,
    fee_rate: float,
    fills: list[GridFill],
) -> None:
    price = levels[index]
    pending_buys.discard(index)
    fills.append(GridFill(side="BUY", time_ms=candle.open_time_ms, price=price, quantity=qty_per_grid, fee_rate=fee_rate))
    if index + 1 < len(levels):
        pending_sells[index + 1] = (price, candle.open_time_ms)


def _fill_sell(
    index: int,
    candle: Candle,
    levels: list[float],
    pending_buys: set[int],
    pending_sells: dict[int, tuple[float, int]],
    qty_per_grid: float,
    fee_rate: float,
    trades: list[GridTrade],
    fills: list[GridFill],
) -> None:
    buy_price, buy_time_ms = pending_sells.pop(index)
    sell_price = levels[index]

    sell_fee = sell_price * qty_per_grid * fee_rate
    buy_fee = buy_price * qty_per_grid * fee_rate
    gross_pnl = (sell_price - buy_price) * qty_per_grid
    net_pnl = gross_pnl - sell_fee - buy_fee

    fills.append(
        GridFill(side="SELL", time_ms=candle.open_time_ms, price=sell_price, quantity=qty_per_grid, fee_rate=fee_rate)
    )
    trades.append(
        GridTrade(
            buy_price=buy_price,
            sell_price=sell_price,
            quantity=qty_per_grid,
            buy_time_ms=buy_time_ms,
            sell_time_ms=candle.open_time_ms,
            gross_pnl_usd=gross_pnl,
            fees_usd=sell_fee + buy_fee,
            net_pnl_usd=net_pnl,
        )
    )
    if index > 0:  # seviye 0'ın altı yok -- kurulumda seed edilmiş bir SAT ise buy_index kavramı yoktur
        pending_buys.add(index - 1)  # hücreyi yeniden kur: fiyat bir alt seviyeye inerse tekrar çalışsın
