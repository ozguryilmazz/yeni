import random

import pytest

from app.backtest.engine import Candle
from app.grid_trading.grid import build_grid_levels, run_grid_backtest


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


def test_run_grid_backtest_no_fills_when_price_stays_between_levels():
    # levels = [90, 95, 100, 105, 110]; start_price=100 -> bekleyen AL: 90 ve 95.
    # Mum hiçbir seviyeye değmiyor -> hiçbir emir dolmamalı.
    candles = [_candle(0, 100.0, 100.5, 99.5, 100.2)]

    result = run_grid_backtest(candles, 90.0, 110.0, grid_count=4, capital_usd=400.0)

    assert result.trades == []
    assert result.fills == []
    assert result.fees_usd == pytest.approx(0.0)
    assert result.open_buy_levels == pytest.approx([90.0, 95.0])
    assert result.open_sell_levels == []


def test_run_grid_backtest_completes_two_round_trips_and_rearms_cells():
    # levels = [90, 95, 100, 105, 110] (grid_count=4); start_price=100 ->
    # bekleyen AL: 90 ve 95. capital_usd=400 -> qty_per_grid = (400/4)/100 = 1.0.
    #
    # Mum 1 (bearish, 100 -> 90): 95'teki ve 90'daki AL emirleri dolar (100'e
    # SAT emri hiç yok çünkü kurulumda üst seviyelere emir konmaz).
    # Mum 2 (bullish, 90 -> 110): 95'teki ve 100'deki (mum 1'de kurulan) SAT
    # emirleri dolar -> iki tamamlanmış işlem (90->95 ve 95->100); 105/110'da
    # hiç emir olmadığından (hiçbir şey oraya kadar alınmadı) orada dolum olmaz.
    candle1 = _candle(0, 100.0, 100.0, 90.0, 90.0)
    candle2 = _candle(60_000, 90.0, 110.0, 90.0, 110.0)

    result = run_grid_backtest([candle1, candle2], 90.0, 110.0, grid_count=4, capital_usd=400.0)

    assert result.qty_per_grid == pytest.approx(1.0)
    assert len(result.trades) == 2

    first, second = result.trades
    assert (first.buy_price, first.sell_price) == pytest.approx((90.0, 95.0))
    assert (second.buy_price, second.sell_price) == pytest.approx((95.0, 100.0))
    assert first.net_pnl_usd == pytest.approx(5.0 - 90 * 1.0 * 0.0002 - 95 * 1.0 * 0.0002)
    assert second.net_pnl_usd == pytest.approx(5.0 - 95 * 1.0 * 0.0002 - 100 * 1.0 * 0.0002)

    assert result.realized_pnl_usd == pytest.approx(first.net_pnl_usd + second.net_pnl_usd)
    assert result.fees_usd == pytest.approx(sum(t.fees_usd for t in result.trades))
    assert result.final_inventory_qty == pytest.approx(0.0)
    assert result.unrealized_pnl_usd == pytest.approx(0.0)
    assert result.total_pnl_usd == pytest.approx(result.realized_pnl_usd)

    # İki hücre de yeniden kuruldu (tekrar en alta indiği takdirde tekrar çalışabilir).
    assert result.open_buy_levels == pytest.approx([90.0, 95.0])
    assert result.open_sell_levels == []

    assert result.min_price_seen == pytest.approx(90.0)
    assert result.max_price_seen == pytest.approx(110.0)
    assert result.breached_lower is True
    assert result.breached_upper is True


def test_run_grid_backtest_tracks_unrealized_loss_when_price_breaches_lower_and_stays():
    # Fiyat gridin tamamını aşağı kırıp geri dönmüyor -> alınan envanter satılamıyor,
    # mark-to-market bir kayıp olarak izlenmeli (stop-loss YOK, bu grid'in doğası).
    candle = _candle(0, 100.0, 100.0, 80.0, 80.0)

    result = run_grid_backtest([candle], 90.0, 110.0, grid_count=4, capital_usd=400.0)

    assert result.trades == []  # hiçbir SAT dolmadı, henüz gerçekleşmiş K/Z yok
    assert result.final_inventory_qty == pytest.approx(2.0)  # 90 ve 95'teki AL'lar doldu
    assert result.breached_lower is True
    assert result.breached_upper is False

    cost_basis = (90.0 * 1.0002) + (95.0 * 1.0002)
    expected_unrealized = 2.0 * 80.0 - cost_basis
    assert result.unrealized_pnl_usd == pytest.approx(expected_unrealized)
    assert result.total_pnl_usd == pytest.approx(expected_unrealized)
    assert result.open_buy_levels == []
    assert result.open_sell_levels == pytest.approx([95.0, 100.0])


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

    recomputed_fees = sum(f.price * f.quantity * 0.0002 for f in result.fills)
    assert result.fees_usd == pytest.approx(recomputed_fees)
    assert result.realized_pnl_usd == pytest.approx(sum(t.net_pnl_usd for t in result.trades))

    if not result.breached_lower and not result.breached_upper:
        assert result.min_price_seen > result.grid_levels[0]
        assert result.max_price_seen < result.grid_levels[-1]
