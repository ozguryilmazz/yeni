from dataclasses import dataclass

from app.backtest.engine import Candle
from app.position_sizing import MAKER_FEE_RATE

DEFAULT_GRID_COUNT = 30
"""Kullanıcı notlarındaki varsayılan: alt/üst sınır arasında 30 eşit parça.
Backtest/canlı öncesi değiştirilebilir."""


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
class GridBacktestResult:
    grid_levels: list[float]
    trades: list[GridTrade]
    fills: list[GridFill]
    realized_pnl_usd: float
    """Tamamlanmış (alım+satım ikilisi kapanmış) hücrelerin toplam net K/Z'ı."""
    unrealized_pnl_usd: float
    """Backtest sonunda hâlâ elde tutulan (satılmamış) envanterin, o envanteri
    almak için ödenen komisyon dahil maliyete göre mark-to-market K/Z'ı."""
    total_pnl_usd: float
    fees_usd: float
    """TÜM dolumlarda (açık pozisyonlar dahil) ödenen toplam komisyon."""
    capital_usd: float
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


def run_grid_backtest(
    candles: list[Candle],
    lower_price: float,
    upper_price: float,
    grid_count: int,
    capital_usd: float,
    maker_fee_rate: float = MAKER_FEE_RATE,
) -> GridBacktestResult:
    """Verilen mum dizisi üzerinde bir arithmetic grid'in AL/SAT dolumlarını
    simüle eder.

    Kurulum: `capital_usd`, `grid_count`'a eşit bölünüp ilk mumun açılışına
    göre SABİT bir taban varlık miktarına (`qty_per_grid`) çevrilir — gerçek
    bir grid botu da kurulumda sabit bir miktar belirler, işlem sırasında
    yeniden hesaplamaz. Başlangıçta mevcut fiyatın ALTINDAKİ her seviyede
    bekleyen bir AL emri vardır (yeterli nakit varsayılır); ÜSTÜNDEKİ
    seviyelerde henüz envanter olmadığından SAT emri yoktur — sıfır
    envanterle başlayan standart 'nötr/long-only' grid davranışı. Bir AL
    dolunca bir üst seviyeye SAT emri konur; o SAT da dolunca kâr
    gerçekleşir ve AYNI alt seviyeye AL emri yeniden kurulur (hücre tekrar
    çalışabilir hale gelir).

    Fiyat aralığın dışına çıkarsa (breached_lower/breached_upper) o yöndeki
    emirler tükenir ve motor kendiliğinden yeni emir açmaz — kalan envanter
    (veya boşta kalan nakit) sadece mark-to-market izlenir; bu fonksiyon bir
    stop-loss uygulamaz (grid stratejisinin doğası budur, kullanıcının ekran
    kartı/ekran notlarında da bir SL tanımlanmamıştır).

    Mum içi gerçek fiyat yolu bilinmediğinden her mum, açılıştan mumun
    KAPANIŞ YÖNÜNE göre önce ZIT uca sonra kapanış yönündeki uca doğru iki
    parçada taranır (bkz. _process_candle) — böylece [low, high] aralığının
    tamamı (sadece net yönü değil) dolum kontrolüne dahil olur."""
    if not candles:
        raise ValueError("Backtest için en az bir mum gerekli")
    if capital_usd <= 0:
        raise ValueError("capital_usd pozitif olmalı")

    levels = build_grid_levels(lower_price, upper_price, grid_count)
    start_price = candles[0].open
    qty_per_grid = (capital_usd / grid_count) / start_price

    pending_buys: set[int] = {i for i, level in enumerate(levels) if level < start_price}
    pending_sells: dict[int, tuple[int, int]] = {}  # sell_level_index -> (buy_level_index, buy_time_ms)

    trades: list[GridTrade] = []
    fills: list[GridFill] = []
    fees_usd = 0.0
    min_price_seen = start_price
    max_price_seen = start_price

    for candle in candles:
        min_price_seen = min(min_price_seen, candle.low)
        max_price_seen = max(max_price_seen, candle.high)
        fees_usd += _process_candle(
            candle, levels, pending_buys, pending_sells, qty_per_grid, maker_fee_rate, trades, fills
        )

    end_price = candles[-1].close
    realized_pnl_usd = sum(t.net_pnl_usd for t in trades)

    final_inventory_qty = len(pending_sells) * qty_per_grid
    cost_basis_usd = sum(
        levels[buy_index] * qty_per_grid * (1 + maker_fee_rate) for buy_index, _ in pending_sells.values()
    )
    final_inventory_value_usd = final_inventory_qty * end_price
    unrealized_pnl_usd = final_inventory_value_usd - cost_basis_usd

    return GridBacktestResult(
        grid_levels=levels,
        trades=trades,
        fills=fills,
        realized_pnl_usd=realized_pnl_usd,
        unrealized_pnl_usd=unrealized_pnl_usd,
        total_pnl_usd=realized_pnl_usd + unrealized_pnl_usd,
        fees_usd=fees_usd,
        capital_usd=capital_usd,
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
    )


def _process_candle(
    candle: Candle,
    levels: list[float],
    pending_buys: set[int],
    pending_sells: dict[int, tuple[int, int]],
    qty_per_grid: float,
    fee_rate: float,
    trades: list[GridTrade],
    fills: list[GridFill],
) -> float:
    """Bu mumda tetiklenen TÜM grid emirlerini işler, toplam komisyonu döner.
    Mum içi yol varsayımı: kapanış açılıştan yüksekse önce açılıştan düşüğe
    (olası bir düşüş), sonra düşükten yükseğe (ralli); kapanış düşükse
    tam tersi. Bu, [low, high] aralığının TAMAMININ (sadece net kapanış
    yönünün değil) dolum kontrolüne girmesini sağlar."""
    common_args = (candle, levels, pending_buys, pending_sells, qty_per_grid, fee_rate, trades, fills)
    if candle.close >= candle.open:
        first = _sweep(*common_args, candle.open, candle.low, ascending=False)
        second = _sweep(*common_args, candle.low, candle.high, ascending=True)
    else:
        first = _sweep(*common_args, candle.open, candle.high, ascending=True)
        second = _sweep(*common_args, candle.high, candle.low, ascending=False)
    return first + second


def _sweep(
    candle: Candle,
    levels: list[float],
    pending_buys: set[int],
    pending_sells: dict[int, tuple[int, int]],
    qty_per_grid: float,
    fee_rate: float,
    trades: list[GridTrade],
    fills: list[GridFill],
    from_price: float,
    to_price: float,
    ascending: bool,
) -> float:
    """`from_price`'tan `to_price`'a TEK YÖNLÜ (monotonik) bir fiyat hareketi
    boyunca tetiklenen emirleri, en yakından en uzağa sırayla işler — bir
    dolumun doğurduğu yeni emir bu sweep'in GERİSİNDE kalıyorsa (ör. bir SAT
    dolumunun yeniden kurduğu AL, aşağıda kalır) bu sweep içinde tekrar
    işlenmez, bir sonraki sweep/mumu bekler; böylece tek yönlü bir fiyat
    hareketi içinde fiziksel olarak imkânsız ileri-geri dolumlar önlenir."""
    lo, hi = (from_price, to_price) if ascending else (to_price, from_price)
    cursor = from_price
    fees = 0.0

    while True:
        if ascending:
            candidates = [i for i in pending_buys if cursor <= levels[i] <= hi]
            candidates += [i for i in pending_sells if cursor <= levels[i] <= hi]
        else:
            candidates = [i for i in pending_buys if lo <= levels[i] <= cursor]
            candidates += [i for i in pending_sells if lo <= levels[i] <= cursor]
        if not candidates:
            break

        next_index = (min if ascending else max)(candidates, key=lambda i: levels[i])
        cursor = levels[next_index]
        if next_index in pending_buys:
            fees += _fill_buy(next_index, candle, levels, pending_buys, pending_sells, qty_per_grid, fee_rate, fills)
        else:
            fees += _fill_sell(
                next_index, candle, levels, pending_buys, pending_sells, qty_per_grid, fee_rate, trades, fills
            )
    return fees


def _fill_buy(
    index: int,
    candle: Candle,
    levels: list[float],
    pending_buys: set[int],
    pending_sells: dict[int, tuple[int, int]],
    qty_per_grid: float,
    fee_rate: float,
    fills: list[GridFill],
) -> float:
    price = levels[index]
    fee = price * qty_per_grid * fee_rate
    pending_buys.discard(index)
    fills.append(GridFill(side="BUY", time_ms=candle.open_time_ms, price=price, quantity=qty_per_grid))
    if index + 1 < len(levels):
        pending_sells[index + 1] = (index, candle.open_time_ms)
    return fee


def _fill_sell(
    index: int,
    candle: Candle,
    levels: list[float],
    pending_buys: set[int],
    pending_sells: dict[int, tuple[int, int]],
    qty_per_grid: float,
    fee_rate: float,
    trades: list[GridTrade],
    fills: list[GridFill],
) -> float:
    buy_index, buy_time_ms = pending_sells.pop(index)
    buy_price = levels[buy_index]
    sell_price = levels[index]

    sell_fee = sell_price * qty_per_grid * fee_rate
    buy_fee = buy_price * qty_per_grid * fee_rate
    gross_pnl = (sell_price - buy_price) * qty_per_grid
    net_pnl = gross_pnl - sell_fee - buy_fee

    fills.append(GridFill(side="SELL", time_ms=candle.open_time_ms, price=sell_price, quantity=qty_per_grid))
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
    pending_buys.add(buy_index)  # hücreyi yeniden kur: fiyat tekrar buy_price'a inerse aynı hücre tekrar çalışsın
    return sell_fee
