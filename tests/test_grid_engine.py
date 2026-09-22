import random

import pytest

from app.backtest.engine import Candle
from app.grid_trading.grid import build_grid_levels, run_grid_backtest
from app.position_sizing import TAKER_FEE_RATE


def _candle(open_time_ms: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(open_time_ms=open_time_ms, open=open_, high=high, low=low, close=close)


def test_build_grid_levels_creates_equal_arithmetic_steps():
    levels = build_grid_levels(100.0, 130.0, grid_count=3)
    assert levels == pytest.approx([100.0, 110.0, 120.0, 130.0])


def test_build_grid_levels_rejects_inverted_bounds():
    with pytest.raises(ValueError):
        build_grid_levels(130.0, 100.0, grid_count=3)


def test_build_grid_levels_rejects_non_positive_grid_count():
    with pytest.raises(ValueError):
        build_grid_levels(100.0, 130.0, grid_count=0)


def test_run_grid_backtest_rejects_empty_candles():
    with pytest.raises(ValueError):
        run_grid_backtest([], 90.0, 110.0, grid_count=4, capital_usd=400.0)


def test_run_grid_backtest_rejects_non_positive_capital():
    candles = [_candle(0, 100.0, 100.0, 100.0, 100.0)]
    with pytest.raises(ValueError):
        run_grid_backtest(candles, 90.0, 110.0, grid_count=4, capital_usd=0.0)


def test_run_grid_backtest_rejects_non_positive_leverage():
    candles = [_candle(0, 100.0, 100.0, 100.0, 100.0)]
    with pytest.raises(ValueError):
        run_grid_backtest(candles, 90.0, 110.0, grid_count=4, capital_usd=400.0, leverage=0.0)


def test_run_grid_backtest_leverage_scales_quantity_pnl_and_fees():
    # Aynı iki mumluk senaryo (bkz. test_run_grid_backtest_seeded_upper_cells_also_
    # complete_round_trips) ama leverage=5 ile -- qty_per_grid, gerçekleşen K/Z ve
    # komisyonların TAMAMI kaldıraçsız hale göre TAM 5 katı olmalı (aynı % fiyat
    # hareketleri, sadece nominal büyüklük ölçekleniyor).
    candle1 = _candle(0, 100.0, 100.0, 90.0, 90.0)
    candle2 = _candle(60_000, 90.0, 110.0, 90.0, 110.0)

    unleveraged = run_grid_backtest([candle1, candle2], 90.0, 110.0, grid_count=4, capital_usd=400.0, leverage=1.0)
    leveraged = run_grid_backtest([candle1, candle2], 90.0, 110.0, grid_count=4, capital_usd=400.0, leverage=5.0)

    assert leveraged.leverage == pytest.approx(5.0)
    assert leveraged.qty_per_grid == pytest.approx(unleveraged.qty_per_grid * 5)
    assert leveraged.realized_pnl_usd == pytest.approx(unleveraged.realized_pnl_usd * 5)
    assert leveraged.fees_usd == pytest.approx(unleveraged.fees_usd * 5)
    assert len(leveraged.trades) == len(unleveraged.trades)


def test_run_grid_backtest_seeds_sells_above_start_price_at_setup():
    # levels = [90, 95, 100, 105, 110]; start_price=100 -> 90/95 AL (<100),
    # 105/110 kurulumda SAT olarak seed edilir (>100, start_price'tan 'piyasadan'
    # alınmış kabul edilir -- gerçek nötr grid botlarının yaptığı gibi); 100
    # start_price'a TAM eşit olduğundan ne AL ne SAT alır (sınırda anlamsız bir
    # anlık wash önlenir). Mum hiçbir seviyeye değmiyor -> ek dolum olmamalı.
    candles = [_candle(0, 100.0, 100.5, 99.5, 100.2)]

    result = run_grid_backtest(candles, 90.0, 110.0, grid_count=4, capital_usd=400.0)

    assert result.trades == []
    assert len(result.fills) == 2  # sadece kurulumdaki 2 seed AL'ı (105 ve 110 için)
    assert all(f.side == "BUY" and f.price == pytest.approx(100.0) for f in result.fills)
    assert result.fees_usd == pytest.approx(2 * 100.0 * 1.0 * TAKER_FEE_RATE)
    assert result.open_buy_levels == pytest.approx([90.0, 95.0])
    assert result.open_sell_levels == pytest.approx([105.0, 110.0])


def test_run_grid_backtest_seeded_upper_cells_also_complete_round_trips():
    # levels = [90, 95, 100, 105, 110] (grid_count=4); start_price=100 ->
    # bekleyen AL: 90 ve 95; SAT (seed, buy_price=100): 105 ve 110.
    # capital_usd=400 -> qty_per_grid = (400/4)/100 = 1.0.
    #
    # Mum 1 (bearish, 100 -> 90): 95'teki ve 90'daki AL emirleri dolar, 100 ve
    # 95'e yeni SAT emirleri kurulur.
    # Mum 2 (bullish, 90 -> 110): SIRAYLA 95, 100, 105, 110'daki SAT emirlerinin
    # HEPSİ dolar -> DÖRT tamamlanmış işlem (90->95, 95->100, ve kurulumda seed
    # edilmiş 100->105, 100->110).
    candle1 = _candle(0, 100.0, 100.0, 90.0, 90.0)
    candle2 = _candle(60_000, 90.0, 110.0, 90.0, 110.0)

    result = run_grid_backtest([candle1, candle2], 90.0, 110.0, grid_count=4, capital_usd=400.0)

    assert result.qty_per_grid == pytest.approx(1.0)
    assert len(result.trades) == 4

    pairs = [(t.buy_price, t.sell_price) for t in result.trades]
    assert pairs == pytest.approx([(90.0, 95.0), (95.0, 100.0), (100.0, 105.0), (100.0, 110.0)])

    # TÜM dolumlarda (kurulum seed'i dahil) tek tip (varsayılan taker) oran uygulanır.
    assert result.trades[0].fees_usd == pytest.approx(90 * TAKER_FEE_RATE + 95 * TAKER_FEE_RATE)
    assert result.trades[2].fees_usd == pytest.approx(100 * TAKER_FEE_RATE + 105 * TAKER_FEE_RATE)

    assert result.realized_pnl_usd == pytest.approx(sum(t.net_pnl_usd for t in result.trades))
    assert result.fees_usd == pytest.approx(sum(t.fees_usd for t in result.trades))
    assert result.final_inventory_qty == pytest.approx(0.0)
    assert result.unrealized_pnl_usd == pytest.approx(0.0)
    assert result.total_pnl_usd == pytest.approx(result.realized_pnl_usd)

    # Dört hücre de yeniden kuruldu (tekrar bir alt seviyeye inerse tekrar çalışabilir).
    assert result.open_buy_levels == pytest.approx([90.0, 95.0, 100.0, 105.0])
    assert result.open_sell_levels == []

    assert result.min_price_seen == pytest.approx(90.0)
    assert result.max_price_seen == pytest.approx(110.0)
    assert result.breached_lower is True
    assert result.breached_upper is True


def test_run_grid_backtest_tracks_unrealized_loss_when_price_breaches_lower_and_stays():
    # Fiyat gridin tamamını aşağı kırıp geri dönmüyor -> hem baştaki AL'lardan
    # (90, 95) hem de seed edilmiş SAT'ların yeniden kurulmuş hallerinden değil,
    # SADECE gerçek AL dolumlarından (90, 95) gelen envanter satılamıyor; seed
    # edilmiş SAT'lar (105, 110) hiç dolmadığı için hâlâ bekliyor. Toplamda 4
    # açık SAT pozisyonu (90->95 bekliyor, 95->100 bekliyor, + 2 seed) var --
    # mark-to-market bir kayıp olarak izlenmeli (stop-loss YOK, bu grid'in doğası).
    candle = _candle(0, 100.0, 100.0, 80.0, 80.0)

    result = run_grid_backtest([candle], 90.0, 110.0, grid_count=4, capital_usd=400.0)

    assert result.trades == []  # hiçbir SAT dolmadı, henüz gerçekleşmiş K/Z yok
    assert result.final_inventory_qty == pytest.approx(4.0)
    assert result.breached_lower is True
    assert result.breached_upper is False

    cost_basis = (90.0 + 95.0 + 2 * 100.0) * (1 + TAKER_FEE_RATE)
    expected_unrealized = 4.0 * 80.0 - cost_basis
    assert result.unrealized_pnl_usd == pytest.approx(expected_unrealized)
    assert result.total_pnl_usd == pytest.approx(expected_unrealized)
    assert result.open_buy_levels == []
    assert result.open_sell_levels == pytest.approx([95.0, 100.0, 105.0, 110.0])


def test_run_grid_backtest_still_trades_when_price_starts_entirely_below_range():
    # Gerçek bug raporu: aralık hesaplaması (ör. Bollinger/destek-direnç) güncel
    # fiyata göre yapılır ama backtest GEÇMİŞE dönük bir pencerede çalışır --
    # o pencerenin başında fiyat aralığın tamamen ALTINDA olabilir. Eskiden bu
    # durumda hiç AL emri kurulamıyordu (hepsi >= start_price) ve envanter de
    # olmadığından hiç SAT emri de oluşamıyordu -> grid tamamen boş kalıp fiyat
    # ne kadar dalgalanırsa dalgalansın SIFIR işlem oluyordu. Artık üst yarı
    # kurulumda seed ediliyor, bu yüzden fiyat aralığa girip normal şekilde
    # dalgalandığında işlem gerçekleşmeli.
    levels_range = (90.0, 110.0)
    candles = [
        _candle(0, 70.0, 71.0, 69.0, 70.0),  # aralığın tamamen altında başlıyor
        _candle(60_000, 70.0, 115.0, 70.0, 100.0),  # aralığın tamamına yükseliyor
        _candle(120_000, 100.0, 105.0, 95.0, 98.0),
    ]

    result = run_grid_backtest(candles, *levels_range, grid_count=4, capital_usd=400.0)

    assert len(result.fills) > 0
    assert len(result.trades) > 0  # eskiden burada her zaman sıfır işlem olurdu


def test_run_grid_backtest_bookkeeping_is_internally_consistent_over_a_long_random_walk():
    # Kesin bir K/Z hesabı değil, iç tutarlılık (muhasebe) değişmezlerini
    # dener: dolum günlüğü ile PnL/komisyon toplamları birbirini tutmalı,
    # tüm işlem fiyatları grid seviyelerinden biri olmalı, envanter negatif
    # olmamalı ve fiyat hiç kırılmadıysa sınır ihlali raporlanmamalı.
    rng = random.Random(123)
    price = 100.0
    candles = []
    for i in range(300):
        open_ = price
        close = max(1.0, open_ + rng.uniform(-1.5, 1.5))
        high = max(open_, close) + abs(rng.uniform(0.0, 0.8))
        low = max(0.01, min(open_, close) - abs(rng.uniform(0.0, 0.8)))
        candles.append(_candle(i * 60_000, open_, high, low, close))
        price = close

    result = run_grid_backtest(candles, 80.0, 120.0, grid_count=30, capital_usd=3000.0)

    def _is_a_grid_level(price: float) -> bool:
        return any(abs(price - level) < 1e-6 for level in result.grid_levels)

    assert all(_is_a_grid_level(t.buy_price) and _is_a_grid_level(t.sell_price) for t in result.trades)

    buy_fills = [f for f in result.fills if f.side == "BUY"]
    sell_fills = [f for f in result.fills if f.side == "SELL"]
    assert len(sell_fills) == len(result.trades)
    assert len(buy_fills) - len(sell_fills) == len(result.open_sell_levels)
    assert result.final_inventory_qty == pytest.approx((len(buy_fills) - len(sell_fills)) * result.qty_per_grid)
    assert result.final_inventory_qty >= 0.0

    recomputed_fees = sum(f.price * f.quantity * f.fee_rate for f in result.fills)
    assert result.fees_usd == pytest.approx(recomputed_fees)
    assert result.realized_pnl_usd == pytest.approx(sum(t.net_pnl_usd for t in result.trades))

    if not result.breached_lower and not result.breached_upper:
        assert result.min_price_seen > result.grid_levels[0]
        assert result.max_price_seen < result.grid_levels[-1]
